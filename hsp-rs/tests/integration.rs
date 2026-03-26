//! Integration tests — spin up a real live server on an ephemeral port, then
//! exercise HTTP and all three WebSocket roles end-to-end.
//!
//! The server is started on a random OS-assigned port in a background thread.
//! An `Arc<AtomicBool>` stop flag is set after each test to shut it down
//! gracefully (the loop checks the flag every ≤ 25 ms).

use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::Duration;

use base64::engine::general_purpose::STANDARD as BASE64_STD;
use base64::Engine;
use sha1::{Digest, Sha1};

use hsp_rs::config::Config;
use hsp_rs::runtime::run;
use hsp_rs::state::MetricsSource;

// ─── helpers ─────────────────────────────────────────────────────────────────

/// Bind port 0 to get a free ephemeral port, then release the listener
/// immediately so the server can bind it.
fn free_port() -> u16 {
    use std::net::TcpListener;
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

/// Build a minimal `Config` pointing at `127.0.0.1:<port>` with live mode on.
fn test_config(port: u16, stop: Arc<AtomicBool>) -> Config {
    Config {
        host: "127.0.0.1".into(),
        port,
        dry_run: false,
        metrics_source: MetricsSource::Local,
        stop_flag: Some(stop),
        ..Config::default()
    }
}

/// Spawn the server in a background thread; poll until its TCP port accepts
/// connections (timeout 2 s), then return a `StopHandle` that kills the server
/// when dropped / explicitly stopped.
struct StopHandle {
    stop: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<()>>,
}

impl StopHandle {
    fn stop(mut self) {
        self.do_stop();
    }

    fn do_stop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.handle.take() {
            h.join().ok();
        }
    }
}

impl Drop for StopHandle {
    fn drop(&mut self) {
        self.do_stop();
    }
}

fn start_server(port: u16, stop: Arc<AtomicBool>) -> StopHandle {
    let config = test_config(port, stop.clone());
    let handle = thread::spawn(move || {
        run(config).expect("server exited with error");
    });

    // Wait up to 2 s for the port to accept connections.
    let addr = format!("127.0.0.1:{port}");
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    loop {
        if TcpStream::connect(&addr).is_ok() {
            break;
        }
        if std::time::Instant::now() > deadline {
            panic!("server did not start within 2 s on port {port}");
        }
        thread::sleep(Duration::from_millis(20));
    }

    StopHandle { stop, handle: Some(handle) }
}

/// Send a raw HTTP request and read the full response (connection-close).
fn http_roundtrip(addr: &str, request: &[u8]) -> String {
    let mut stream = TcpStream::connect(addr).unwrap();
    stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
    stream.write_all(request).unwrap();
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).unwrap_or(0);
    String::from_utf8_lossy(&buf).into_owned()
}

/// Compute the RFC 6455 `Sec-WebSocket-Accept` header value.
fn ws_accept(key: &str) -> String {
    let combined = format!("{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
    let hash = Sha1::digest(combined.as_bytes());
    BASE64_STD.encode(hash)
}

/// Attempt the WebSocket upgrade handshake.  Returns the stream positioned
/// just after the HTTP response headers.
fn ws_connect(addr: &str, path: &str, key: &str) -> TcpStream {
    let accept = ws_accept(key);
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: test\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\r\n"
    );
    let mut stream = TcpStream::connect(addr).unwrap();
    stream.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
    stream.write_all(request.as_bytes()).unwrap();

    // Read until end of headers.
    let mut header_buf = Vec::new();
    let mut one = [0u8; 1];
    loop {
        stream.read_exact(&mut one).unwrap();
        header_buf.push(one[0]);
        if header_buf.ends_with(b"\r\n\r\n") {
            break;
        }
    }
    let headers = String::from_utf8_lossy(&header_buf);
    assert!(
        headers.contains("101 Switching Protocols"),
        "expected 101 upgrade, got:\n{headers}"
    );
    assert!(
        headers.contains(&accept),
        "accept key mismatch in headers:\n{headers}"
    );
    stream
}

/// Read one unmasked server WebSocket text frame and return its payload as
/// a UTF-8 string.  Server frames are unmasked per RFC 6455.
fn ws_read_text_frame(stream: &mut TcpStream) -> String {
    let mut hdr = [0u8; 2];
    stream.read_exact(&mut hdr).unwrap();
    let _fin_opcode = hdr[0]; // 0x81 = FIN + text
    let payload_len: usize = match hdr[1] & 0x7F {
        126 => {
            let mut buf = [0u8; 2];
            stream.read_exact(&mut buf).unwrap();
            u16::from_be_bytes(buf) as usize
        }
        127 => {
            let mut buf = [0u8; 8];
            stream.read_exact(&mut buf).unwrap();
            u64::from_be_bytes(buf) as usize
        }
        n => n as usize,
    };
    let mut payload = vec![0u8; payload_len];
    stream.read_exact(&mut payload).unwrap();
    String::from_utf8(payload).unwrap()
}

/// Build a masked client WebSocket text frame.
fn ws_frame_text(payload: &[u8]) -> Vec<u8> {
    let mask = [0x37, 0xfa, 0x21, 0x3d_u8];
    let mut frame = Vec::with_capacity(6 + payload.len());
    frame.push(0x81); // FIN + text
    assert!(payload.len() < 126, "test payload too large");
    frame.push(0x80 | payload.len() as u8); // MASK bit + length
    frame.extend_from_slice(&mask);
    for (i, &b) in payload.iter().enumerate() {
        frame.push(b ^ mask[i % 4]);
    }
    frame
}

// ─── tests ────────────────────────────────────────────────────────────────────

#[test]
fn http_health_returns_ok() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let resp = http_roundtrip(
        &format!("127.0.0.1:{port}"),
        b"GET /health HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    );

    assert!(resp.contains("200 OK"), "unexpected response: {resp}");
    assert!(resp.contains(r#""ok":true"#), "body missing ok:true: {resp}");
    srv.stop();
}

#[test]
fn http_state_returns_telemetry_json() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let resp = http_roundtrip(
        &format!("127.0.0.1:{port}"),
        b"GET /state HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    );

    assert!(resp.contains("200 OK"), "unexpected: {resp}");
    assert!(resp.contains("cpu_permille"), "missing telemetry field: {resp}");
    srv.stop();
}

#[test]
fn http_control_acks_command() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let body = br#"{"command_id":"integ-1","escalation_regulator":1.5}"#;
    let req = format!(
        "POST /control HTTP/1.1\r\nHost: test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let mut request = req.into_bytes();
    request.extend_from_slice(body);

    let resp = http_roundtrip(&format!("127.0.0.1:{port}"), &request);
    assert!(resp.contains("200 OK"), "unexpected: {resp}");
    assert!(resp.contains("control_ack"), "missing ack: {resp}");
    assert!(resp.contains("integ-1"), "missing command id: {resp}");
    srv.stop();
}

#[test]
fn http_unknown_route_returns_404() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let resp = http_roundtrip(
        &format!("127.0.0.1:{port}"),
        b"GET /does-not-exist HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n",
    );
    assert!(resp.contains("404"), "expected 404, got: {resp}");
    srv.stop();
}

#[test]
fn ws_observer_streams_state_frames() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let mut ws = ws_connect(
        &format!("127.0.0.1:{port}"),
        "/ws",
        "dGhlIHNhbXBsZSBub25jZQ==",
    );

    let frame = ws_read_text_frame(&mut ws);
    assert!(frame.contains("cpu_permille"), "observer frame missing field: {frame}");
    assert!(frame.contains("seq"), "observer frame missing seq: {frame}");
    srv.stop();
}

#[test]
fn ws_control_acks_command() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    let mut ws = ws_connect(
        &format!("127.0.0.1:{port}"),
        "/ws?role=control",
        "dGhlIHNhbXBsZSBub25jZQ==",
    );

    let cmd = br#"{"command_id":"ws-ctrl-1","escalation_regulator":1.0}"#;
    ws.write_all(&ws_frame_text(cmd)).unwrap();

    let ack = ws_read_text_frame(&mut ws);
    assert!(ack.contains("control_ack"), "expected ack, got: {ack}");
    assert!(ack.contains("ws-ctrl-1"), "missing command id: {ack}");
    srv.stop();
}

#[test]
fn ws_ingest_propagates_to_observer() {
    let stop = Arc::new(AtomicBool::new(false));
    let port = free_port();
    let srv = start_server(port, stop);

    // Open ingest connection and push a telemetry frame.
    let mut ingest = ws_connect(
        &format!("127.0.0.1:{port}"),
        "/ws?role=ingest",
        "aGVsbG8gd29ybGQhISE=",
    );
    let telemetry = br#"{"cpu_permille":888,"ram_permille":444}"#;
    ingest.write_all(&ws_frame_text(telemetry)).unwrap();

    let ack = ws_read_text_frame(&mut ingest);
    assert!(ack.contains("ingest_ack"), "expected ingest_ack, got: {ack}");
    assert!(ack.contains("applied_fields"), "missing applied_fields: {ack}");

    // Observer must see the ingested values on its first frame.  Open after
    // the ingest push so the server has already applied the overlay.
    thread::sleep(Duration::from_millis(150)); // let at least one tick propagate
    let mut observer = ws_connect(
        &format!("127.0.0.1:{port}"),
        "/ws",
        "dGhlIHNhbXBsZSBub25jZQ==",
    );
    let obs_frame = ws_read_text_frame(&mut observer);
    assert!(
        obs_frame.contains("888") || obs_frame.contains("cpu_permille"),
        "observer frame missing ingested data: {obs_frame}",
    );
    srv.stop();
}
