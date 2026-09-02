// =============================================================================
// @project    ELY — Exactly Like You
// @file       ios/ELY/Theme/ELYTheme.swift
// @brief      Design system — colors, typography and cyberpunk theme constants
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

import SwiftUI

// MARK: - ELY Theme Colors

enum ELYTheme {
    // Backgrounds
    static let bgPrimary = Color(hex: "#0a0a0f")
    static let bgSecondary = Color(hex: "#12121a")
    static let bgTertiary = Color(hex: "#1a1a2e")

    // Text
    static let textPrimary = Color(hex: "#e0e0e8")
    static let textSecondary = Color(hex: "#a0a0b0")
    static let textMuted = Color(hex: "#6b7280")

    // Accents
    static let cyberCyan = Color(hex: "#00e5ff")
    static let cyberCyanDim = Color(hex: "#00b8d4")

    // Borders
    static let borderDim = Color(hex: "#1e1e2e")
    static let borderActive = Color(hex: "#00e5ff").opacity(0.4)

    // Status
    static let dangerRed = Color(hex: "#ef4444")
    static let successGreen = Color(hex: "#22c55e")
    static let warningAmber = Color(hex: "#f59e0b")

    // Message bubbles
    static let userBubble = Color(hex: "#00e5ff").opacity(0.15)
    static let assistantBubble = Color(hex: "#1a1a2e")

    // Gradients
    static let glowGradient = LinearGradient(
        colors: [cyberCyan.opacity(0.3), cyberCyan.opacity(0.0)],
        startPoint: .top,
        endPoint: .bottom
    )

    // Corner radius
    static let cornerRadiusSmall: CGFloat = 8
    static let cornerRadiusMedium: CGFloat = 12
    static let cornerRadiusLarge: CGFloat = 16
    static let cornerRadiusPill: CGFloat = 24
}

// MARK: - Color hex initializer

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: // RGB (12-bit)
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: // RGB (24-bit)
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB (32-bit)
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (255, 0, 0, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}

// MARK: - View modifiers

struct ELYCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(ELYTheme.bgSecondary)
            .clipShape(RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusMedium))
            .overlay(
                RoundedRectangle(cornerRadius: ELYTheme.cornerRadiusMedium)
                    .stroke(ELYTheme.borderDim, lineWidth: 1)
            )
    }
}

extension View {
    func elyCard() -> some View {
        modifier(ELYCardModifier())
    }
}
