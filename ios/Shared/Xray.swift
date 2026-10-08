import Foundation
import LibXray

/// libXray's single entry point: JSON request in, JSON response out (apiVersion 3).
enum Xray {
    struct Response {
        let success: Bool
        let data: Any?
        let error: String
    }

    static func invoke(_ method: String, _ payload: [String: Any] = [:]) -> Response {
        let request: [String: Any] = ["apiVersion": 3, "method": method, "payload": payload]
        guard let body = try? JSONSerialization.data(withJSONObject: request),
              let text = String(data: body, encoding: .utf8)
        else { return Response(success: false, data: nil, error: "bad request") }
        let raw: String = LibXrayInvoke(text) ?? ""
        guard let json = (try? JSONSerialization.jsonObject(with: Data(raw.utf8))) as? [String: Any] else {
            return Response(success: false, data: nil, error: "bad response")
        }
        return Response(
            success: json["success"] as? Bool ?? false,
            data: json["data"],
            error: json["error"] as? String ?? ""
        )
    }

    static func run(_ config: String) -> Response { invoke("runXray", ["xrayJson": config]) }

    static func stop() { _ = invoke("stopXray") }

    static var version: String {
        (invoke("xrayVersion").data as? [String: Any])?["version"] as? String ?? "?"
    }
}
