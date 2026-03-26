use std::fmt;
use std::io::{self, ErrorKind, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::fd::{AsRawFd, RawFd};
use std::time::Instant;

use base64::engine::general_purpose::STANDARD as BASE64_STD;
use base64::Engine;
use sha1::{Digest, Sha1};

use crate::clock::update_clock;
use crate::config::Config;
use crate::control::{apply_control_command, parse_control_frame, DedupeCache};
use crate::encode::encode_ui_snapshot;
use crate::http::PreloadedHttp;
use crate::mapper::map_frame;
use crate::midi::{MidiError, MidiOutput};
use crate::protocol::ControlError;
use crate::state::{
    AudioStyle, ClockState, MetricsSource, MidiEvent, RuntimeState, TelemetryFrame, TickPlan,
    UiFrame,
};
use crate::telemetry::{
    sample_fast, sample_slow, update_external_overlay, TelemetryError, TelemetryState,
};
use crate::ws::{ClientRole, ClientSlab};

const MAX_LIVE_CLIENTS: usize = 16;
const MAX_HTTP_BUFFER_BYTES: usize = 64 * 1024;
const CONTROL_PATH: &str = "/control";
const WS_PATH: &str = "/ws";
const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

#[derive(Debug)]
pub enum RuntimeError {
    Io(io::Error),
    Control(ControlError),
    Midi(MidiError),
    Telemetry(TelemetryError),
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "io error: {error}"),
            Self::Control(error) => write!(f, "control error: {error}"),
            Self::Midi(error) => write!(f, "midi error: {error}"),
            Self::Telemetry(error) => write!(f, "telemetry error: {error}"),
        }
    }
}

impl std::error::Error for RuntimeError {}

impl From<io::Error> for RuntimeError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<ControlError> for RuntimeError {
    fn from(value: ControlError) -> Self {
        Self::Control(value)
    }
}

impl From<MidiError> for RuntimeError {
    fn from(value: MidiError) -> Self {
        Self::Midi(value)
    }
}

impl From<TelemetryError> for RuntimeError {
    fn from(value: TelemetryError) -> Self {
        Self::Telemetry(value)
    }
}

pub fn run(config: Config) -> Result<(), RuntimeError> {
    let http = PreloadedHttp::load(config.index_html.as_deref())?;
    let mut runtime_state = RuntimeState::new(
        config.experience_profile,
        config.metrics_source,
        AudioStyle::Droid,
        config.escalation_permille,
        config.ui_publish_hz,
    );
    let mut telemetry_state = TelemetryState::default();
    let mut clock_state = ClockState::new(
        config.base_sample_millihz,
        config.min_sample_millihz,
        config.max_sample_millihz,
        config.escalation_permille,
    );
    let mut frame = TelemetryFrame::default();
    let mut midi = MidiOutput::open(config.midi_port_hint.as_deref())?;
    let mut dedupe = DedupeCache::new();
    let clients = ClientSlab::<MAX_LIVE_CLIENTS>::new();

    if midi.enabled {
        if let Some(port_name) = midi.port_name.as_deref() {
            println!("hsp-rs midi output enabled on: {port_name}");
        }
    } else if let Some(port_hint) = config.midi_port_hint.as_deref() {
        println!("hsp-rs midi output disabled (no output ports found; hint='{port_hint}')");
    } else {
        println!("hsp-rs midi output disabled (no output ports found)");
    }

    sample_fast(
        0,
        &mut frame,
        &mut telemetry_state,
        runtime_state.metrics_source == MetricsSource::External,
    )?;
    sample_slow(0, &mut frame, &mut telemetry_state)?;

    let bootstrap_command = parse_control_frame(br#"{"command_id":"bootstrap-1","escalation_regulator":1.0}"#)?;
    let bootstrap_ack = apply_control_command(&bootstrap_command, &mut runtime_state, &mut dedupe);
    let mut tick = update_clock(&mut clock_state, &frame);
    let mut event = MidiEvent::default();
    map_frame(&frame, &runtime_state, &tick, &mut event);
    midi.emit(&event, 0)?;

    let ui_frame = UiFrame::from_runtime(&frame, &runtime_state, &tick, &event, clock_state.current_millihz);
    let mut ui_buffer = [0u8; 512];
    let ui_len = encode_ui_snapshot(&ui_frame, &mut ui_buffer);

    let epoll_loop = EpollLoop::new(tick.interval_ms.max(1))?;
    let _ = epoll_loop.wait_once(0)?;
    let _ = epoll_loop.consume_tick()?;

    println!(
        "hsp-rs starter initialized: html={} bytes, ws_max_size={} bytes, ws_max_queue={}, ui_snapshot={} bytes, tick={} ms, clients={}, ack={}",
        http.content_len(),
        config.ws_max_size_bytes,
        config.ws_max_queue,
        ui_len,
        tick.interval_ms,
        clients.active_count(),
        bootstrap_ack.to_json(),
    );

    if config.dry_run {
        return Ok(());
    }

    run_live_loop(
        &config,
        &http,
        &mut runtime_state,
        &mut telemetry_state,
        &mut clock_state,
        &mut frame,
        &mut tick,
        &mut event,
        &mut midi,
        &mut dedupe,
        &epoll_loop,
    )
}

fn run_live_loop(
    config: &Config,
    http: &PreloadedHttp,
    runtime_state: &mut RuntimeState,
    telemetry_state: &mut TelemetryState,
    clock_state: &mut ClockState,
    frame: &mut TelemetryFrame,
    tick: &mut TickPlan,
    event: &mut MidiEvent,
    midi: &mut MidiOutput,
    dedupe: &mut DedupeCache,
    epoll_loop: &EpollLoop,
) -> Result<(), RuntimeError> {
    let bind_addr = format!("{}:{}", config.host, config.port);
    let listener = TcpListener::bind(&bind_addr)?;
    listener.set_nonblocking(true)?;

    println!(
        "hsp-rs live loop listening on {} (GET /, GET /state, GET /health, POST /control, WS /ws)",
        bind_addr
    );

    let mut client_slab = ClientSlab::<MAX_LIVE_CLIENTS>::new();
    let mut clients = Vec::<LiveClient>::with_capacity(MAX_LIVE_CLIENTS);
    let started = Instant::now();
    let mut last_slow_ms = 0u32;
    let mut current_interval_ms = tick.interval_ms.max(1);

    loop {
        if config.should_stop() {
            break Ok(());
        }
        accept_pending_clients(&listener, &mut clients, &mut client_slab)?;
        let now_ms = monotonic_ms(started);

        let ui_frame = UiFrame::from_runtime(frame, runtime_state, tick, event, clock_state.current_millihz);
        let mut ui_buffer = [0u8; 512];
        let ui_len = encode_ui_snapshot(&ui_frame, &mut ui_buffer);

        process_clients(
            &mut clients,
            &mut client_slab,
            http,
            runtime_state,
            telemetry_state,
            dedupe,
            &ui_buffer[..ui_len],
            frame.seq,
            now_ms,
            config.ws_max_size_bytes.max(MAX_HTTP_BUFFER_BYTES),
        )?;

        if !epoll_loop.wait_once(25)? {
            midi.tick_note_off(now_ms)?;
            continue;
        }

        let expirations = epoll_loop.consume_tick()?.max(1).min(8);
        for _ in 0..expirations {
            let now_ms = monotonic_ms(started);
            sample_fast(
                now_ms,
                frame,
                telemetry_state,
                runtime_state.metrics_source == MetricsSource::External,
            )?;

            if now_ms.saturating_sub(last_slow_ms) >= 1_000 {
                sample_slow(now_ms, frame, telemetry_state)?;
                last_slow_ms = now_ms;
            }

            *tick = update_clock(clock_state, frame);
            let target_interval = tick.interval_ms.max(1);
            if target_interval != current_interval_ms {
                epoll_loop.set_interval(target_interval)?;
                current_interval_ms = target_interval;
            }

            runtime_state.phrase_step = runtime_state.phrase_step.wrapping_add(1);
            map_frame(frame, runtime_state, tick, event);
            midi.emit(event, now_ms)?;
        }
    }
}

fn monotonic_ms(started: Instant) -> u32 {
    started.elapsed().as_millis().min(u32::MAX as u128) as u32
}

fn accept_pending_clients(
    listener: &TcpListener,
    clients: &mut Vec<LiveClient>,
    slab: &mut ClientSlab<MAX_LIVE_CLIENTS>,
) -> io::Result<()> {
    loop {
        match listener.accept() {
            Ok((mut stream, peer)) => {
                stream.set_nonblocking(true)?;

                if clients.len() >= MAX_LIVE_CLIENTS {
                    let _ = write_http_response(
                        &mut stream,
                        503,
                        "application/json",
                        br#"{"ok":false,"message":"server at capacity"}"#,
                    );
                    continue;
                }

                if let Some(slot_index) = slab.allocate(stream.as_raw_fd(), ClientRole::Observer) {
                    clients.push(LiveClient::new(stream, peer, slot_index));
                } else {
                    let _ = write_http_response(
                        &mut stream,
                        503,
                        "application/json",
                        br#"{"ok":false,"message":"server at capacity"}"#,
                    );
                }
            }
            Err(error) if error.kind() == ErrorKind::WouldBlock => break,
            Err(error) => return Err(error),
        }
    }

    Ok(())
}

fn process_clients(
    clients: &mut Vec<LiveClient>,
    slab: &mut ClientSlab<MAX_LIVE_CLIENTS>,
    http: &PreloadedHttp,
    runtime_state: &mut RuntimeState,
    telemetry_state: &mut TelemetryState,
    dedupe: &mut DedupeCache,
    ui_payload: &[u8],
    ui_seq: u32,
    now_ms: u32,
    max_request_bytes: usize,
) -> Result<(), RuntimeError> {
    let mut index = 0usize;
    while index < clients.len() {
        let mut should_close = false;

        match try_handle_client(
            &mut clients[index],
            slab,
            http,
            runtime_state,
            telemetry_state,
            dedupe,
            ui_payload,
            ui_seq,
            now_ms,
            max_request_bytes,
        )? {
            ClientAction::Keep => {
                index += 1;
            }
            ClientAction::Close => {
                should_close = true;
            }
        }

        if should_close {
            let slot_index = clients[index].slot_index;
            slab.release(slot_index);
            clients.swap_remove(index);
        }
    }

    Ok(())
}

fn try_handle_client(
    client: &mut LiveClient,
    slab: &mut ClientSlab<MAX_LIVE_CLIENTS>,
    http: &PreloadedHttp,
    runtime_state: &mut RuntimeState,
    telemetry_state: &mut TelemetryState,
    dedupe: &mut DedupeCache,
    ui_payload: &[u8],
    ui_seq: u32,
    now_ms: u32,
    max_request_bytes: usize,
) -> Result<ClientAction, RuntimeError> {
    if let ClientTransport::WebSocket { role } = client.transport {
        return try_handle_ws_client(
            client,
            role,
            runtime_state,
            telemetry_state,
            dedupe,
            ui_payload,
            ui_seq,
            now_ms,
            max_request_bytes,
        );
    }

    let mut chunk = [0u8; 2048];
    loop {
        match client.stream.read(&mut chunk) {
            Ok(0) => return Ok(ClientAction::Close),
            Ok(n) => {
                client.buffer.extend_from_slice(&chunk[..n]);
                if client.buffer.len() > max_request_bytes {
                    let _ = write_http_response(
                        &mut client.stream,
                        413,
                        "application/json",
                        br#"{"ok":false,"message":"request too large"}"#,
                    );
                    return Ok(ClientAction::Close);
                }
            }
            Err(error) if error.kind() == ErrorKind::WouldBlock => break,
            Err(error) => return Err(RuntimeError::Io(error)),
        }
    }

    match parse_http_request(&client.buffer, max_request_bytes) {
        RequestParse::Incomplete => Ok(ClientAction::Keep),
        RequestParse::Invalid(message) => {
            let body = format!("{{\"ok\":false,\"message\":\"{}\"}}", message).into_bytes();
            let _ = write_http_response(&mut client.stream, 400, "application/json", &body);
            Ok(ClientAction::Close)
        }
        RequestParse::Ready(request) => {
            match handle_http_request(
                &mut client.stream,
                http,
                runtime_state,
                dedupe,
                ui_payload,
                request,
            )? {
                HttpOutcome::Close => Ok(ClientAction::Close),
                HttpOutcome::Upgraded(role) => {
                    client.transport = ClientTransport::WebSocket { role };
                    client.buffer.clear();
                    client.last_published_seq = 0;
                    slab.set_role(client.slot_index, role);
                    Ok(ClientAction::Keep)
                }
            }
        }
    }
}

fn handle_http_request(
    stream: &mut TcpStream,
    http: &PreloadedHttp,
    runtime_state: &mut RuntimeState,
    dedupe: &mut DedupeCache,
    ui_payload: &[u8],
    request: HttpRequest<'_>,
) -> Result<HttpOutcome, RuntimeError> {
    let (path, query) = split_path_query(request.path);

    match (request.method, path) {
        ("GET", "/") => {
            write_http_response(stream, 200, "text/html; charset=utf-8", &http.index_html)?;
            Ok(HttpOutcome::Close)
        }
        ("GET", "/health") => {
            write_http_response(stream, 200, "application/json", br#"{"ok":true}"#)?;
            Ok(HttpOutcome::Close)
        }
        ("GET", "/state") => {
            write_http_response(stream, 200, "application/json", ui_payload)?;
            Ok(HttpOutcome::Close)
        }
        ("POST", CONTROL_PATH) => match parse_control_frame(request.body) {
            Ok(command) => {
                let ack = apply_control_command(&command, runtime_state, dedupe);
                let ack_json = ack.to_json();
                write_http_response(stream, 200, "application/json", ack_json.as_bytes())?;
                Ok(HttpOutcome::Close)
            }
            Err(error) => {
                let error_json = error.to_json();
                write_http_response(stream, 400, "application/json", error_json.as_bytes())?;
                Ok(HttpOutcome::Close)
            }
        },
        ("GET", WS_PATH) => {
            if !request.is_websocket_upgrade() {
                write_http_response(
                    stream,
                    400,
                    "application/json",
                    br#"{"ok":false,"message":"expected websocket upgrade headers"}"#,
                )?;
                return Ok(HttpOutcome::Close);
            }

            let Some(ws_key) = request.ws_key else {
                write_http_response(
                    stream,
                    400,
                    "application/json",
                    br#"{"ok":false,"message":"missing Sec-WebSocket-Key"}"#,
                )?;
                return Ok(HttpOutcome::Close);
            };

            let role = parse_ws_role(query);
            write_websocket_handshake(stream, ws_key)?;
            Ok(HttpOutcome::Upgraded(role))
        }
        _ => {
            write_http_response(stream, 404, "application/json", br#"{"ok":false,"message":"not found"}"#)?;
            Ok(HttpOutcome::Close)
        }
    }
}

fn write_http_response(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &[u8],
) -> io::Result<()> {
    let reason = status_text(status);
    let headers = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n",
        status,
        reason,
        content_type,
        body.len(),
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body)?;
    Ok(())
}

fn status_text(status: u16) -> &'static str {
    match status {
        200 => "OK",
        400 => "Bad Request",
        404 => "Not Found",
        413 => "Payload Too Large",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "Unknown",
    }
}

struct LiveClient {
    stream: TcpStream,
    slot_index: usize,
    buffer: Vec<u8>,
    transport: ClientTransport,
    last_published_seq: u32,
}

impl LiveClient {
    fn new(stream: TcpStream, _peer: std::net::SocketAddr, slot_index: usize) -> Self {
        Self {
            stream,
            slot_index,
            buffer: Vec::with_capacity(2048),
            transport: ClientTransport::Http,
            last_published_seq: 0,
        }
    }
}

enum ClientAction {
    Keep,
    Close,
}

enum HttpOutcome {
    Close,
    Upgraded(ClientRole),
}

#[derive(Copy, Clone)]
enum ClientTransport {
    Http,
    WebSocket { role: ClientRole },
}

#[derive(Copy, Clone)]
struct HttpRequest<'a> {
    method: &'a str,
    path: &'a str,
    body: &'a [u8],
    ws_key: Option<&'a str>,
    connection_header: Option<&'a str>,
    upgrade_header: Option<&'a str>,
}

impl<'a> HttpRequest<'a> {
    fn is_websocket_upgrade(&self) -> bool {
        let has_upgrade_token = self
            .connection_header
            .map(|value| {
                value
                    .split(',')
                    .any(|token| token.trim().eq_ignore_ascii_case("upgrade"))
            })
            .unwrap_or(false);
        let is_websocket = self
            .upgrade_header
            .map(|value| value.trim().eq_ignore_ascii_case("websocket"))
            .unwrap_or(false);
        has_upgrade_token && is_websocket
    }
}

enum RequestParse<'a> {
    Incomplete,
    Invalid(&'static str),
    Ready(HttpRequest<'a>),
}

fn parse_http_request(buffer: &[u8], max_body_bytes: usize) -> RequestParse<'_> {
    let Some(header_end) = find_subslice(buffer, b"\r\n\r\n") else {
        return RequestParse::Incomplete;
    };

    let header_bytes = &buffer[..header_end];
    let header_text = match std::str::from_utf8(header_bytes) {
        Ok(text) => text,
        Err(_) => return RequestParse::Invalid("invalid request headers"),
    };

    let mut lines = header_text.split("\r\n");
    let request_line = match lines.next() {
        Some(line) if !line.is_empty() => line,
        _ => return RequestParse::Invalid("missing request line"),
    };

    let mut request_parts = request_line.split_whitespace();
    let method = match request_parts.next() {
        Some(method) => method,
        None => return RequestParse::Invalid("missing HTTP method"),
    };
    let path = match request_parts.next() {
        Some(path) => path,
        None => return RequestParse::Invalid("missing request path"),
    };

    let mut content_length = 0usize;
    let mut ws_key = None;
    let mut connection_header = None;
    let mut upgrade_header = None;
    for line in lines {
        let mut parts = line.splitn(2, ':');
        let name = parts.next().unwrap_or("").trim();
        let value = parts.next().unwrap_or("").trim();
        if name.eq_ignore_ascii_case("content-length") {
            match value.parse::<usize>() {
                Ok(parsed) => content_length = parsed,
                Err(_) => return RequestParse::Invalid("invalid Content-Length"),
            }
        } else if name.eq_ignore_ascii_case("sec-websocket-key") {
            ws_key = Some(value);
        } else if name.eq_ignore_ascii_case("connection") {
            connection_header = Some(value);
        } else if name.eq_ignore_ascii_case("upgrade") {
            upgrade_header = Some(value);
        }
    }

    if content_length > max_body_bytes {
        return RequestParse::Invalid("request body exceeds limit");
    }

    let body_start = header_end + 4;
    let Some(body_end) = body_start.checked_add(content_length) else {
        return RequestParse::Invalid("invalid Content-Length");
    };
    if body_end > buffer.len() {
        return RequestParse::Incomplete;
    }

    RequestParse::Ready(HttpRequest {
        method,
        path,
        body: &buffer[body_start..body_end],
        ws_key,
        connection_header,
        upgrade_header,
    })
}

fn split_path_query(path: &str) -> (&str, Option<&str>) {
    match path.split_once('?') {
        Some((head, query)) => (head, Some(query)),
        None => (path, None),
    }
}

fn parse_ws_role(query: Option<&str>) -> ClientRole {
    let Some(query) = query else {
        return ClientRole::Observer;
    };

    for part in query.split('&') {
        let Some((key, value)) = part.split_once('=') else {
            continue;
        };
        if key.eq_ignore_ascii_case("role") {
            if value.eq_ignore_ascii_case("control") {
                return ClientRole::Control;
            }
            if value.eq_ignore_ascii_case("ingest") {
                return ClientRole::Ingest;
            }
        }
    }

    ClientRole::Observer
}

fn write_websocket_handshake(stream: &mut TcpStream, ws_key: &str) -> io::Result<()> {
    let accept = websocket_accept_key(ws_key);
    let response = format!(
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
        accept,
    );
    stream.write_all(response.as_bytes())?;
    Ok(())
}

fn websocket_accept_key(client_key: &str) -> String {
    let mut hasher = Sha1::new();
    hasher.update(client_key.trim().as_bytes());
    hasher.update(WS_GUID.as_bytes());
    BASE64_STD.encode(hasher.finalize())
}

#[derive(Debug)]
struct IngestParseError {
    code: &'static str,
    message: String,
}

fn parse_ingest_text_frame(payload: &[u8], now_ms: u32) -> Result<(TelemetryFrame, usize), IngestParseError> {
    let text = std::str::from_utf8(payload).map_err(|_| IngestParseError {
        code: "invalid_utf8",
        message: String::from("ingest frame must be valid UTF-8"),
    })?;
    let body = text.trim();
    if !(body.starts_with('{') && body.ends_with('}')) {
        return Err(IngestParseError {
            code: "invalid_json_shape",
            message: String::from("ingest frame must be a flat JSON object"),
        });
    }

    let mut frame = TelemetryFrame {
        now_ms,
        source: MetricsSource::External,
        ..TelemetryFrame::default()
    };
    let mut field_count = 0usize;

    let inner = body[1..body.len() - 1].trim();
    if !inner.is_empty() {
        for pair in inner.split(',') {
            let mut parts = pair.splitn(2, ':');
            let key = parse_json_key(parts.next().unwrap_or(""))?;
            let value = parts.next().ok_or_else(|| IngestParseError {
                code: "invalid_json_shape",
                message: String::from("missing ingest field value"),
            })?;

            match key {
                "cpu_permille" => frame.cpu_permille = parse_u16_field(value, key)?,
                "ram_permille" => frame.ram_permille = parse_u16_field(value, key)?,
                "gpu_permille" => frame.gpu_permille = parse_u16_field(value, key)?,
                "swap_permille" => frame.swap_permille = parse_u16_field(value, key)?,
                "iowait_permille" => frame.iowait_permille = parse_u16_field(value, key)?,
                "load1_permille" => frame.load1_permille = parse_u16_field(value, key)?,
                "disk_busy_permille" => frame.disk_busy_permille = parse_u16_field(value, key)?,
                "gpu_mem_permille" => frame.gpu_mem_permille = parse_u16_field(value, key)?,

                "cpu_temp_deci_c" => frame.cpu_temp_deci_c = parse_i16_field(value, key)?,
                "gpu_temp_deci_c" => frame.gpu_temp_deci_c = parse_i16_field(value, key)?,
                "storage_temp_deci_c" => frame.storage_temp_deci_c = parse_i16_field(value, key)?,

                "cpu_freq_mhz" => frame.cpu_freq_mhz = parse_u16_field(value, key)?,
                "proc_count" => frame.proc_count = parse_u16_field(value, key)?,

                "power_deci_w" => frame.power_deci_w = parse_i16_field(value, key)?,
                "gpu_power_deci_w" => frame.gpu_power_deci_w = parse_i16_field(value, key)?,
                "battery_power_deci_w" => frame.battery_power_deci_w = parse_i16_field(value, key)?,

                "disk_kib_s" => frame.disk_kib_s = parse_u32_field(value, key)?,
                "net_kib_s" => frame.net_kib_s = parse_u32_field(value, key)?,
                "net_pps" => frame.net_pps = parse_u32_field(value, key)?,
                "disk_iops" => frame.disk_iops = parse_u32_field(value, key)?,
                "ctx_switches_ps" => frame.ctx_switches_ps = parse_u32_field(value, key)?,
                "interrupts_ps" => frame.interrupts_ps = parse_u32_field(value, key)?,

                "net_errors_ps" => frame.net_errors_ps = parse_u16_field(value, key)?,
                "net_drops_ps" => frame.net_drops_ps = parse_u16_field(value, key)?,

                "flags" => frame.flags = parse_u8_field(value, key)?,
                "source" => {
                    let parsed_source = parse_json_key(value)?;
                    if !parsed_source.eq_ignore_ascii_case("external") {
                        return Err(IngestParseError {
                            code: "invalid_source",
                            message: String::from("ingest source must be external"),
                        });
                    }
                    frame.source = MetricsSource::External;
                }
                other => {
                    return Err(IngestParseError {
                        code: "unknown_field",
                        message: format!("unknown ingest field: {other}"),
                    })
                }
            }

            field_count = field_count.saturating_add(1);
        }
    }

    if field_count == 0 {
        return Err(IngestParseError {
            code: "no_fields",
            message: String::from("ingest frame must include at least one known field"),
        });
    }

    Ok((frame, field_count))
}

fn ingest_error_json(code: &str, message: &str) -> String {
    format!(
        "{{\"type\":\"ingest_error\",\"ok\":false,\"code\":\"{}\",\"message\":\"{}\"}}",
        code,
        message.replace('"', "'")
    )
}

fn parse_json_key(raw: &str) -> Result<&str, IngestParseError> {
    let trimmed = raw.trim();
    if !(trimmed.starts_with('"') && trimmed.ends_with('"') && trimmed.len() >= 2) {
        return Err(IngestParseError {
            code: "invalid_json_shape",
            message: String::from("expected JSON string key/value"),
        });
    }
    Ok(&trimmed[1..trimmed.len() - 1])
}

fn parse_numeric_value(raw: &str, field: &str) -> Result<f64, IngestParseError> {
    let trimmed = raw.trim().trim_matches('"');
    let value = trimmed.parse::<f64>().map_err(|_| IngestParseError {
        code: "invalid_number",
        message: format!("{field} must be numeric"),
    })?;
    if !value.is_finite() {
        return Err(IngestParseError {
            code: "invalid_number",
            message: format!("{field} must be finite"),
        });
    }
    Ok(value)
}

fn parse_u8_field(raw: &str, field: &str) -> Result<u8, IngestParseError> {
    let value = parse_numeric_value(raw, field)?;
    if !(0.0..=u8::MAX as f64).contains(&value) {
        return Err(IngestParseError {
            code: "out_of_range",
            message: format!("{field} out of range for u8"),
        });
    }
    Ok(value.round() as u8)
}

fn parse_u16_field(raw: &str, field: &str) -> Result<u16, IngestParseError> {
    let value = parse_numeric_value(raw, field)?;
    if !(0.0..=u16::MAX as f64).contains(&value) {
        return Err(IngestParseError {
            code: "out_of_range",
            message: format!("{field} out of range for u16"),
        });
    }
    Ok(value.round() as u16)
}

fn parse_i16_field(raw: &str, field: &str) -> Result<i16, IngestParseError> {
    let value = parse_numeric_value(raw, field)?;
    if !(i16::MIN as f64..=i16::MAX as f64).contains(&value) {
        return Err(IngestParseError {
            code: "out_of_range",
            message: format!("{field} out of range for i16"),
        });
    }
    Ok(value.round() as i16)
}

fn parse_u32_field(raw: &str, field: &str) -> Result<u32, IngestParseError> {
    let value = parse_numeric_value(raw, field)?;
    if !(0.0..=u32::MAX as f64).contains(&value) {
        return Err(IngestParseError {
            code: "out_of_range",
            message: format!("{field} out of range for u32"),
        });
    }
    Ok(value.round() as u32)
}

fn try_handle_ws_client(
    client: &mut LiveClient,
    role: ClientRole,
    runtime_state: &mut RuntimeState,
    telemetry_state: &mut TelemetryState,
    dedupe: &mut DedupeCache,
    ui_payload: &[u8],
    ui_seq: u32,
    now_ms: u32,
    max_payload_bytes: usize,
) -> Result<ClientAction, RuntimeError> {
    let mut chunk = [0u8; 2048];
    loop {
        match client.stream.read(&mut chunk) {
            Ok(0) => return Ok(ClientAction::Close),
            Ok(n) => {
                client.buffer.extend_from_slice(&chunk[..n]);
                if client.buffer.len() > max_payload_bytes.saturating_mul(2) {
                    return Ok(ClientAction::Close);
                }
            }
            Err(error) if error.kind() == ErrorKind::WouldBlock => break,
            Err(error) => return Err(RuntimeError::Io(error)),
        }
    }

    loop {
        match decode_ws_frame(&mut client.buffer, max_payload_bytes) {
            WsDecode::Incomplete => break,
            WsDecode::ProtocolError(message) => {
                eprintln!("closing websocket client after protocol error: {message}");
                return Ok(ClientAction::Close);
            }
            WsDecode::Frame(frame) => {
                match frame.opcode {
                    0x1 => {
                        if role == ClientRole::Control {
                            match parse_control_frame(&frame.payload) {
                                Ok(command) => {
                                    let ack = apply_control_command(&command, runtime_state, dedupe);
                                    write_ws_text_frame(&mut client.stream, ack.to_json().as_bytes())?;
                                }
                                Err(error) => {
                                    write_ws_text_frame(&mut client.stream, error.to_json().as_bytes())?;
                                }
                            }
                        } else if role == ClientRole::Ingest {
                            match parse_ingest_text_frame(&frame.payload, now_ms) {
                                Ok((ingest_frame, field_count)) => {
                                    update_external_overlay(telemetry_state, ingest_frame, now_ms);
                                    let ack = format!(
                                        "{{\"type\":\"ingest_ack\",\"ok\":true,\"applied_fields\":{},\"metrics_source\":\"{}\"}}",
                                        field_count,
                                        runtime_state.metrics_source.as_str(),
                                    );
                                    write_ws_text_frame(&mut client.stream, ack.as_bytes())?;
                                }
                                Err(error) => {
                                    let payload = ingest_error_json(error.code, &error.message);
                                    write_ws_text_frame(&mut client.stream, payload.as_bytes())?;
                                }
                            }
                        }
                    }
                    0x8 => {
                        let _ = write_ws_close_frame(&mut client.stream);
                        return Ok(ClientAction::Close);
                    }
                    0x9 => {
                        write_ws_pong_frame(&mut client.stream, &frame.payload)?;
                    }
                    0xA => {}
                    _ => {
                        return Ok(ClientAction::Close);
                    }
                }
            }
        }
    }

    if role == ClientRole::Observer && client.last_published_seq != ui_seq {
        if write_ws_text_frame(&mut client.stream, ui_payload).is_err() {
            return Ok(ClientAction::Close);
        }
        client.last_published_seq = ui_seq;
    }

    Ok(ClientAction::Keep)
}

#[derive(Debug)]
enum WsDecode {
    Incomplete,
    ProtocolError(&'static str),
    Frame(WsFrame),
}

#[derive(Debug)]
struct WsFrame {
    opcode: u8,
    payload: Vec<u8>,
}

fn decode_ws_frame(buffer: &mut Vec<u8>, max_payload_bytes: usize) -> WsDecode {
    if buffer.len() < 2 {
        return WsDecode::Incomplete;
    }

    let b0 = buffer[0];
    let b1 = buffer[1];
    let fin = (b0 & 0x80) != 0;
    let opcode = b0 & 0x0F;
    if !fin {
        return WsDecode::ProtocolError("fragmented frames are not supported");
    }

    let masked = (b1 & 0x80) != 0;
    if !masked {
        return WsDecode::ProtocolError("client websocket frames must be masked");
    }

    let mut offset = 2usize;
    let payload_len = match b1 & 0x7F {
        n @ 0..=125 => n as usize,
        126 => {
            if buffer.len() < offset + 2 {
                return WsDecode::Incomplete;
            }
            let len = u16::from_be_bytes([buffer[offset], buffer[offset + 1]]) as usize;
            offset += 2;
            len
        }
        127 => {
            if buffer.len() < offset + 8 {
                return WsDecode::Incomplete;
            }
            let len = u64::from_be_bytes([
                buffer[offset],
                buffer[offset + 1],
                buffer[offset + 2],
                buffer[offset + 3],
                buffer[offset + 4],
                buffer[offset + 5],
                buffer[offset + 6],
                buffer[offset + 7],
            ]);
            offset += 8;
            if len > usize::MAX as u64 {
                return WsDecode::ProtocolError("payload too large");
            }
            len as usize
        }
        _ => return WsDecode::ProtocolError("invalid websocket length encoding"),
    };

    if payload_len > max_payload_bytes {
        return WsDecode::ProtocolError("payload exceeds configured limit");
    }

    if buffer.len() < offset + 4 + payload_len {
        return WsDecode::Incomplete;
    }

    let mask_key = [
        buffer[offset],
        buffer[offset + 1],
        buffer[offset + 2],
        buffer[offset + 3],
    ];
    offset += 4;

    let payload_end = offset + payload_len;
    let mut payload = buffer[offset..payload_end].to_vec();
    for (index, byte) in payload.iter_mut().enumerate() {
        *byte ^= mask_key[index % 4];
    }

    buffer.drain(0..payload_end);
    WsDecode::Frame(WsFrame { opcode, payload })
}

fn write_ws_frame(stream: &mut TcpStream, opcode: u8, payload: &[u8]) -> io::Result<()> {
    let mut header = [0u8; 10];
    header[0] = 0x80 | (opcode & 0x0F);

    let header_len = if payload.len() <= 125 {
        header[1] = payload.len() as u8;
        2
    } else if payload.len() <= u16::MAX as usize {
        header[1] = 126;
        let len = (payload.len() as u16).to_be_bytes();
        header[2] = len[0];
        header[3] = len[1];
        4
    } else {
        header[1] = 127;
        let len = (payload.len() as u64).to_be_bytes();
        header[2..10].copy_from_slice(&len);
        10
    };

    stream.write_all(&header[..header_len])?;
    stream.write_all(payload)?;
    Ok(())
}

fn write_ws_text_frame(stream: &mut TcpStream, payload: &[u8]) -> io::Result<()> {
    write_ws_frame(stream, 0x1, payload)
}

fn write_ws_pong_frame(stream: &mut TcpStream, payload: &[u8]) -> io::Result<()> {
    write_ws_frame(stream, 0xA, payload)
}

fn write_ws_close_frame(stream: &mut TcpStream) -> io::Result<()> {
    write_ws_frame(stream, 0x8, &[])
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return None;
    }

    haystack.windows(needle.len()).position(|window| window == needle)
}

struct EpollLoop {
    epoll_fd: RawFd,
    timer_fd: RawFd,
}

impl EpollLoop {
    fn new(interval_ms: u16) -> io::Result<Self> {
        let epoll_fd = unsafe { libc::epoll_create1(libc::EPOLL_CLOEXEC) };
        if epoll_fd < 0 {
            return Err(io::Error::last_os_error());
        }

        let timer_fd = unsafe {
            libc::timerfd_create(libc::CLOCK_MONOTONIC, libc::TFD_CLOEXEC | libc::TFD_NONBLOCK)
        };
        if timer_fd < 0 {
            let error = io::Error::last_os_error();
            unsafe {
                libc::close(epoll_fd);
            }
            return Err(error);
        }

        let timer_spec = libc::itimerspec {
            it_interval: timespec_from_ms(interval_ms),
            it_value: timespec_from_ms(interval_ms),
        };
        if unsafe { libc::timerfd_settime(timer_fd, 0, &timer_spec, std::ptr::null_mut()) } < 0 {
            let error = io::Error::last_os_error();
            unsafe {
                libc::close(timer_fd);
                libc::close(epoll_fd);
            }
            return Err(error);
        }

        let mut event = libc::epoll_event {
            events: libc::EPOLLIN as u32,
            u64: timer_fd as u64,
        };
        if unsafe { libc::epoll_ctl(epoll_fd, libc::EPOLL_CTL_ADD, timer_fd, &mut event) } < 0 {
            let error = io::Error::last_os_error();
            unsafe {
                libc::close(timer_fd);
                libc::close(epoll_fd);
            }
            return Err(error);
        }

        Ok(Self { epoll_fd, timer_fd })
    }

    fn wait_once(&self, timeout_ms: i32) -> io::Result<bool> {
        let mut event = unsafe { std::mem::zeroed::<libc::epoll_event>() };
        let ready = unsafe { libc::epoll_wait(self.epoll_fd, &mut event, 1, timeout_ms) };
        if ready < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(ready > 0)
    }

    fn consume_tick(&self) -> io::Result<u64> {
        let mut expirations = 0u64;
        let read_len = unsafe {
            libc::read(
                self.timer_fd,
                (&mut expirations as *mut u64).cast::<libc::c_void>(),
                std::mem::size_of::<u64>(),
            )
        };

        if read_len < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == ErrorKind::WouldBlock {
                return Ok(0);
            }
            return Err(error);
        }

        Ok(expirations)
    }

    fn set_interval(&self, interval_ms: u16) -> io::Result<()> {
        let timer_spec = libc::itimerspec {
            it_interval: timespec_from_ms(interval_ms),
            it_value: timespec_from_ms(interval_ms),
        };
        if unsafe { libc::timerfd_settime(self.timer_fd, 0, &timer_spec, std::ptr::null_mut()) }
            < 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

impl Drop for EpollLoop {
    fn drop(&mut self) {
        if self.timer_fd >= 0 {
            unsafe {
                libc::close(self.timer_fd);
            }
        }
        if self.epoll_fd >= 0 {
            unsafe {
                libc::close(self.epoll_fd);
            }
        }
    }
}

fn timespec_from_ms(interval_ms: u16) -> libc::timespec {
    let interval_ms = interval_ms.max(1) as i64;
    libc::timespec {
        tv_sec: interval_ms / 1_000,
        tv_nsec: (interval_ms % 1_000) * 1_000_000,
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_http_request, parse_ingest_text_frame, websocket_accept_key, RequestParse};

    #[test]
    fn parses_simple_get_request() {
        let request = b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n";
        match parse_http_request(request, 1024) {
            RequestParse::Ready(parsed) => {
                assert_eq!(parsed.method, "GET");
                assert_eq!(parsed.path, "/health");
                assert!(parsed.body.is_empty());
            }
            _ => panic!("expected parsed request"),
        }
    }

    #[test]
    fn parses_post_with_content_length() {
        let request = b"POST /control HTTP/1.1\r\nHost: localhost\r\nContent-Length: 11\r\n\r\n{\"ok\":true}";
        match parse_http_request(request, 1024) {
            RequestParse::Ready(parsed) => {
                assert_eq!(parsed.method, "POST");
                assert_eq!(parsed.path, "/control");
                assert_eq!(parsed.body, b"{\"ok\":true}");
            }
            _ => panic!("expected parsed request"),
        }
    }

    #[test]
    fn computes_rfc_websocket_accept_key() {
        let accept = websocket_accept_key("dGhlIHNhbXBsZSBub25jZQ==");
        assert_eq!(accept, "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=");
    }

    #[test]
    fn detects_websocket_upgrade_request() {
        let request = b"GET /ws?role=control HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n";
        match parse_http_request(request, 1024) {
            RequestParse::Ready(parsed) => {
                assert_eq!(parsed.method, "GET");
                assert_eq!(parsed.path, "/ws?role=control");
                assert!(parsed.is_websocket_upgrade());
                assert_eq!(parsed.ws_key, Some("dGhlIHNhbXBsZSBub25jZQ=="));
            }
            _ => panic!("expected parsed request"),
        }
    }

    #[test]
    fn parses_ingest_frame_with_known_fields() {
        let payload = br#"{"cpu_permille":750,"ram_permille":500}"#;
        match parse_ingest_text_frame(payload, 1000) {
            Ok((frame, count)) => {
                assert_eq!(frame.cpu_permille, 750);
                assert_eq!(frame.ram_permille, 500);
                assert_eq!(count, 2);
            }
            Err(e) => panic!("unexpected ingest error: {} {}", e.code, e.message),
        }
    }

    #[test]
    fn rejects_ingest_frame_with_no_fields() {
        let payload = br#"{}"#;
        assert!(parse_ingest_text_frame(payload, 0).is_err());
    }

    #[test]
    fn rejects_ingest_frame_with_unknown_field() {
        let payload = br#"{"bogus_metric":1}"#;
        let err = parse_ingest_text_frame(payload, 0).unwrap_err();
        assert_eq!(err.code, "unknown_field");
    }
}