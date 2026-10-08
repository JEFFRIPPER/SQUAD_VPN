import SwiftUI

/// Colors of the Android app (ui/glass/Tokens.kt).
enum Palette {
    static let red = Color(hex: 0xD00018)
    static let red4 = Color(hex: 0x82000F)
    static let plum = Color(hex: 0x4A0E2A)
    static let top = Color(hex: 0x140306)
    static let bottom = Color(hex: 0x050102)
    static let glass = Color(hex: 0x0C0204)
    static let text = Color(hex: 0xF6EAEA)
    static let textDim = Color(hex: 0xCFB3B3)
    static let good = Color(hex: 0x7BD88F)
    static let warn = Color(hex: 0xFFB86B)
    static let bad = Color(hex: 0xFF6B76)

    static func ping(_ ms: Int?) -> Color {
        guard let ms else { return textDim }
        if ms < 0 { return bad }
        return ms < 300 ? good : ms < 800 ? warn : bad
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// Dark red backdrop with slowly drifting glow blobs.
struct Backdrop: View {
    var active: Bool
    @State private var drift = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Palette.top, Palette.bottom], startPoint: .top, endPoint: .bottom)
            Circle().fill(Palette.red.opacity(active ? 0.55 : 0.35))
                .frame(width: 340).blur(radius: 90)
                .offset(x: drift ? 90 : -80, y: drift ? -260 : -180)
            Circle().fill(Palette.red4.opacity(0.45))
                .frame(width: 300).blur(radius: 100)
                .offset(x: drift ? -110 : 70, y: drift ? 260 : 330)
            Circle().fill(Palette.plum.opacity(0.6))
                .frame(width: 260).blur(radius: 90)
                .offset(x: drift ? 120 : -40, y: drift ? 80 : 20)
        }
        .ignoresSafeArea()
        .animation(.easeInOut(duration: 1.2), value: active)
        .onAppear {
            withAnimation(.easeInOut(duration: 9).repeatForever(autoreverses: true)) { drift.toggle() }
        }
    }
}

/// A frosted glass card.
struct Glass: ViewModifier {
    var radius: CGFloat = 24

    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial.opacity(0.85), in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .background(Palette.glass.opacity(0.35), in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [.white.opacity(0.22), Palette.red.opacity(0.18)],
                                                 startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
            )
    }
}

extension View {
    func glass(_ radius: CGFloat = 24) -> some View { modifier(Glass(radius: radius)) }
}

/// The project mark: an inverted pentagram in a ring (as on the Android tile).
struct Pentagram: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 24
        let o = CGPoint(x: rect.midX - 12 * s, y: rect.midY - 12 * s)
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: o.x + x * s, y: o.y + y * s) }
        var path = Path()
        path.addEllipse(in: CGRect(x: o.x + 1.6 * s, y: o.y + 1.6 * s, width: 20.8 * s, height: 20.8 * s))
        path.move(to: p(12, 20.6))
        path.addLine(to: p(6.95, 5.04))
        path.addLine(to: p(20.18, 14.66))
        path.addLine(to: p(3.82, 14.66))
        path.addLine(to: p(17.05, 5.04))
        path.closeSubpath()
        return path
    }
}

/// Press feedback: a springy shrink.
struct SpringPress: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.55), value: configuration.isPressed)
    }
}
