//! hermes-village-engine: the village rules as a line-oriented JSON service.
//!
//! One JSON request per line on stdin, one JSON response per line on stdout; exits when
//! stdin closes. It opens no socket, reads no environment secret, writes no file and never
//! updates itself.

mod engine;
mod ops;
mod pyfmt;
mod rng;
mod rules;
mod terrain;
mod world;

use serde_json::{json, Value};
use std::io::{BufRead, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};

fn respond(line: &str) -> Value {
    let req: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => return json!({"id": null, "ok": false, "error": format!("bad request: {}", e)}),
    };
    let id = req.get("id").cloned().unwrap_or(Value::Null);
    match catch_unwind(AssertUnwindSafe(|| ops::handle(&req))) {
        Ok(Ok(resp)) => resp,
        Ok(Err(e)) => json!({"id": id, "ok": false, "error": e}),
        Err(panic) => {
            let msg = panic
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| panic.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_else(|| "unknown panic".into());
            json!({"id": id, "ok": false, "error": format!("panic: {}", msg), "panic": true})
        }
    }
}

fn main() {
    std::panic::set_hook(Box::new(|_| {})); // the panic text is returned in the response
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let resp = respond(&line);
        if writeln!(out, "{}", resp).is_err() || out.flush().is_err() {
            break;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hello_reports_the_rules_hash() {
        let r = respond(r#"{"id": 1, "op": "hello"}"#);
        assert_eq!(r["ok"], true);
        assert_eq!(r["result"]["rules_sha256"], rules::rules().sha256);
        assert_eq!(r["result"]["protocol"], ops::PROTOCOL);
    }

    #[test]
    fn a_bad_request_is_an_error_response_not_a_crash() {
        assert_eq!(respond("not json")["ok"], false);
        assert_eq!(respond(r#"{"id": 2, "op": "nope", "world": {}}"#)["ok"], false);
        let r = respond(r#"{"id": 3, "op": "_land", "args": {"seed": 5, "cx": 0}}"#);
        assert_eq!(r["ok"], false);
        assert_eq!(r["id"], 3);
    }

    #[test]
    fn a_panic_is_caught_and_the_next_request_still_works() {
        let r = catch_unwind(|| -> i32 { panic!("boom") });
        assert!(r.is_err());
        assert_eq!(respond(r#"{"id": 4, "op": "hello"}"#)["ok"], true);
    }
}
