import SwiftUI

struct MainView: View {
    @EnvironmentObject var model: AppModel
    @State private var showServers = false
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Backdrop(active: model.state == .on)
            ScrollView(showsIndicators: false) {
                VStack(spacing: 22) {
                    header
                    PowerButton(state: model.state) { model.toggle() }
                        .padding(.top, 8)
                    status
                    serverCard
                    profiles
                    toggles
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 30)
            }
        }
        .sheet(isPresented: $showServers) { ServersView().environmentObject(model) }
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model) }
    }

    private var header: some View {
        HStack {
            Pentagram().stroke(Palette.red, style: StrokeStyle(lineWidth: 1.6, lineJoin: .round))
                .frame(width: 28, height: 28)
            Text("SQUAD VPN").font(.system(size: 22, weight: .heavy, design: .rounded)).foregroundStyle(Palette.text)
            Spacer()
            Button { showSettings = true } label: {
                Image(systemName: "gearshape.fill").font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(Palette.text).frame(width: 44, height: 44).glass(22)
            }
            .buttonStyle(SpringPress())
            .accessibilityLabel("Настройки")
        }
        .padding(.top, 8)
    }

    private var status: some View {
        VStack(spacing: 6) {
            Text(title)
                .font(.system(size: 26, weight: .bold, design: .rounded))
                .foregroundStyle(model.state == .on ? Palette.good : Palette.text)
                .contentTransition(.opacity)
                .animation(.easeInOut, value: model.state)
            if model.state == .on, let since = model.connectedSince {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(Self.duration(context.date.timeIntervalSince(since)))
                        .font(.system(.body, design: .monospaced)).foregroundStyle(Palette.textDim)
                }
            }
            if !model.stage.isEmpty {
                Text(model.stage).font(.footnote).foregroundStyle(Palette.textDim).multilineTextAlignment(.center)
            }
            if let message = model.message {
                Text(message).font(.footnote).foregroundStyle(Palette.warn).multilineTextAlignment(.center)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: model.message)
    }

    private var title: String {
        switch model.state {
        case .off: return "Отключено"
        case .connecting: return "Подключение…"
        case .on: return "Защищено"
        case .stopping: return "Отключаю…"
        }
    }

    static func duration(_ seconds: TimeInterval) -> String {
        let s = Int(max(0, seconds))
        return String(format: "%02d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
    }

    private var serverCard: some View {
        Button { showServers = true } label: {
            HStack(spacing: 14) {
                Image(systemName: "server.rack").font(.title3).foregroundStyle(Palette.red)
                    .frame(width: 42, height: 42)
                    .background(Palette.red.opacity(0.15), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.selected == nil && model.connectedNode == nil ? "Сервер: самый быстрый" : "Сервер")
                        .font(.caption).foregroundStyle(Palette.textDim)
                    Text(model.currentNode?.name ?? (model.nodes.isEmpty ? "Загружаю подписку…" : "Выберу при подключении"))
                        .font(.headline).foregroundStyle(Palette.text).lineLimit(1)
                }
                Spacer()
                if let node = model.currentNode, let ms = model.pings[node.id] {
                    Text(ms < 0 ? "нет" : "\(ms) мс").font(.subheadline.monospacedDigit()).foregroundStyle(Palette.ping(ms))
                }
                Image(systemName: "chevron.right").foregroundStyle(Palette.textDim)
            }
            .padding(14)
            .glass()
        }
        .buttonStyle(SpringPress())
    }

    private var profiles: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Подписка").font(.caption).foregroundStyle(Palette.textDim).padding(.leading, 4)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(Profile.allCases) { profile in
                    let on = model.profile == profile
                    Button {
                        withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) { model.setProfile(profile) }
                    } label: {
                        Text(profile.title).font(.subheadline.weight(.semibold))
                            .foregroundStyle(on ? .white : Palette.text)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(on ? AnyShapeStyle(LinearGradient(colors: [Palette.red, Palette.red4], startPoint: .top, endPoint: .bottom)) : AnyShapeStyle(Color.clear),
                                        in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .glass(14)
                    }
                    .buttonStyle(SpringPress())
                }
            }
            Text(model.profile.hint).font(.footnote).foregroundStyle(Palette.textDim).padding(.horizontal, 4)
                .animation(.easeInOut, value: model.profile)
        }
    }

    private var toggles: some View {
        HStack(spacing: 10) {
            chip("Обход DPI", "scissors", $model.antiDPI)
            chip("РФ-сайты напрямую", "arrow.triangle.branch", $model.ruDirect)
        }
    }

    private func chip(_ title: String, _ icon: String, _ value: Binding<Bool>) -> some View {
        Button {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { value.wrappedValue.toggle() }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: value.wrappedValue ? "checkmark.circle.fill" : icon)
                Text(title).lineLimit(1).minimumScaleFactor(0.8)
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(value.wrappedValue ? Palette.good : Palette.textDim)
            .frame(maxWidth: .infinity, minHeight: 40)
            .glass(20)
        }
        .buttonStyle(SpringPress())
    }
}

/// The big round button with the pentagram: breathes while connecting, glows when on.
struct PowerButton: View {
    let state: VpnState
    let action: () -> Void
    @State private var spin = false
    @State private var breathe = false

    var body: some View {
        Button {
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            action()
        } label: {
            ZStack {
                Circle()
                    .fill(Palette.red.opacity(state == .on ? 0.45 : 0.12))
                    .frame(width: 250, height: 250)
                    .blur(radius: 40)
                    .scaleEffect(breathe && state != .off ? 1.08 : 0.95)
                Circle()
                    .fill(LinearGradient(colors: state == .on ? [Palette.red, Palette.red4] : [Color(hex: 0x2A0A0E), Color(hex: 0x120305)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 200, height: 200)
                    .overlay(Circle().strokeBorder(.white.opacity(0.15), lineWidth: 1))
                    .shadow(color: Palette.red.opacity(state == .on ? 0.7 : 0.2), radius: state == .on ? 30 : 10)
                if state == .connecting || state == .stopping {
                    Circle()
                        .trim(from: 0, to: 0.28)
                        .stroke(Palette.red, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                        .frame(width: 222, height: 222)
                        .rotationEffect(.degrees(spin ? 360 : 0))
                        .animation(.linear(duration: 1).repeatForever(autoreverses: false), value: spin)
                        .onAppear { spin = true }
                        .onDisappear { spin = false }
                }
                Pentagram()
                    .stroke(state == .on ? .white : Palette.red, style: StrokeStyle(lineWidth: 1.4, lineJoin: .round))
                    .frame(width: 110, height: 110)
                    .scaleEffect(state == .on ? 1.05 : 1)
            }
        }
        .buttonStyle(SpringPress())
        .animation(.spring(response: 0.5, dampingFraction: 0.6), value: state)
        .accessibilityLabel(state == .on ? "Отключить VPN" : "Подключить VPN")
        .onAppear {
            withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) { breathe = true }
        }
    }
}
