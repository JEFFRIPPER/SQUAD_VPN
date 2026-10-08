import SwiftUI
import UIKit

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var custom = Prefs.customURL

    var body: some View {
        NavigationStack {
            ZStack {
                Backdrop(active: false)
                Form {
                    Section {
                        Toggle("Русские сайты напрямую", isOn: $model.ruDirect)
                        Toggle("Обход DPI (дробить TLS)", isOn: $model.antiDPI)
                    } header: {
                        Text("Подключение")
                    } footer: {
                        Text("Банки и госуслуги часто не пускают иностранные адреса, поэтому .ru идут мимо VPN. В «Белых списках» это всегда выключено. Изменения действуют со следующего подключения.")
                    }
                    .listRowBackground(Palette.glass.opacity(0.55))

                    Section {
                        TextField("https://… или vless://…", text: $custom, axis: .vertical)
                            .lineLimit(1...4)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        Button("Вставить из буфера") {
                            if let text = UIPasteboard.general.string { custom = text }
                        }
                        Button("Сохранить и выбрать «Своя ссылка»") {
                            model.setCustom(custom)
                            dismiss()
                        }
                        .disabled(!custom.contains("://"))
                    } header: {
                        Text("Своя подписка или ключи")
                    }
                    .listRowBackground(Palette.glass.opacity(0.55))

                    Section {
                        Button("Обновить подписку сейчас") {
                            Task { await model.reload(force: true); model.startCheck() }
                        }
                        Link("Страница проекта на GitHub", destination: URL(string: "https://github.com/JEFFRIPPER/SQUAD_VPN/releases")!)
                    }
                    .listRowBackground(Palette.glass.opacity(0.55))

                    Section {
                        HStack {
                            Text("Версия")
                            Spacer()
                            Text(AppModel.version).foregroundStyle(Palette.textDim)
                        }
                    } footer: {
                        Text("SQUAD VPN бесплатный. Серверы публичные, их собирает и проверяет проект каждый час.")
                    }
                    .listRowBackground(Palette.glass.opacity(0.55))
                }
                .scrollContentBackground(.hidden)
                .tint(Palette.red)
            }
            .navigationTitle("Настройки")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Готово") { dismiss() } }
            }
        }
        .preferredColorScheme(.dark)
    }
}
