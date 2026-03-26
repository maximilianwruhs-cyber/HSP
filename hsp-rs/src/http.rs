use std::fs;
use std::io;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct PreloadedHttp {
    pub index_html: Vec<u8>,
}

impl PreloadedHttp {
    pub fn load(path: Option<&Path>) -> io::Result<Self> {
        let index_html = match path {
            Some(path) => fs::read(path)?,
            None => default_index_html().into_bytes(),
        };
        Ok(Self { index_html })
    }

    pub fn content_len(&self) -> usize {
        self.index_html.len()
    }
}

fn default_index_html() -> String {
    String::from(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>hsp-rs</title></head><body><h1>hsp-rs starter skeleton</h1></body></html>",
    )
}
