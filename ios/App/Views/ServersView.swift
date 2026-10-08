import SwiftUI

struct ServersView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Backdrop(active: false)
                List {
                    Section {
                        row(title: "Самый быстрый", subtitle: "Выберу сам по пингу", ms: nil, chosen: model.selected == nil) {
                            model.select(nil)
                        }
                    }
                    Section {
                        ForEach(model.sortedNodes) { node in
                            row(title: node.name, subtitle: "\(node.proto) · \(node.server)", ms: model.pings[node.id],
                                chosen: model.selected == node.id) {
                                model.select(node.id)
                            }
                        }
                    } header: {
                        Text("\(model.profile.title): \(model.nodes.count) серверов, живых \(model.aliveCount)")
                    }
                }
                .scrollContentBackground(.hidden)
                .refreshable { await model.reload(force: true); model.startCheck() }
            }
            .navigationTitle("Серверы")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Готово") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    if let progress = model.progress {
                        Button { model.stopCheck() } label: {
                            HStack(spacing: 6) {
                                ProgressView().controlSize(.small)
                                Text("\(progress.done)/\(progress.total)").monospacedDigit()
                            }
                        }
                        .accessibilityLabel("Остановить проверку")
                    } else {
                        Button("Проверить") { model.startCheck() }
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                Toggle("Скрывать неработающие", isOn: $model.hideDead)
                    .font(.subheadline).tint(Palette.red)
                    .padding(.horizontal, 16).padding(.vertical, 12)
                    .glass(18).padding(.horizontal, 16).padding(.bottom, 6)
            }
        }
        .preferredColorScheme(.dark)
    }

    private func row(title: String, subtitle: String, ms: Int?, chosen: Bool, action: @escaping () -> Void) -> some View {
        Button {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) { action() }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: chosen ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(chosen ? Palette.red : Palette.textDim)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(Palette.text).lineLimit(1)
                    Text(subtitle).font(.caption).foregroundStyle(Palette.textDim).lineLimit(1)
                }
                Spacer()
                if let ms {
                    Text(ms < 0 ? "нет ответа" : "\(ms) мс")
                        .font(.footnote.monospacedDigit()).foregroundStyle(Palette.ping(ms))
                }
            }
        }
        .listRowBackground(Palette.glass.opacity(0.55))
    }
}
