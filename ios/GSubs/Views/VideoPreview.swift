import AVKit
import SwiftUI

struct VideoPreview: View {
    let videoURL: URL
    let cues: [SubtitleCue]
    let style: SubtitleStyle

    @State private var player: AVPlayer
    @State private var currentTime = 0.0

    init(videoURL: URL, cues: [SubtitleCue], style: SubtitleStyle) {
        self.videoURL = videoURL
        self.cues = cues
        self.style = style
        _player = State(initialValue: AVPlayer(url: videoURL))
    }

    var body: some View {
        VideoPlayer(player: player) {
            GeometryReader { proxy in
                if let cue = cues.first(where: { $0.contains(currentTime) }) {
                    Text(cue.text.uppercased())
                        .font(.system(size: 22 * style.fontScale, weight: .black))
                        .multilineTextAlignment(.center)
                        .foregroundStyle(style.foreground.color)
                        .shadow(color: .black, radius: 1, x: 2, y: 2)
                        .padding(.horizontal, 18)
                        .frame(maxWidth: .infinity)
                        .position(
                            x: proxy.size.width / 2,
                            y: proxy.size.height * (1 - style.bottomOffset - 0.06)
                        )
                }
            }
        }
        .aspectRatio(9 / 16, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(.white.opacity(0.12)))
        .task {
            while !Task.isCancelled {
                let seconds = player.currentTime().seconds
                currentTime = seconds.isFinite ? seconds : 0
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
        .onDisappear { player.pause() }
    }
}

private extension SubtitleColor {
    var color: Color {
        switch self {
        case .yellow: .yellow
        case .white: .white
        case .cyan: .cyan
        }
    }
}
