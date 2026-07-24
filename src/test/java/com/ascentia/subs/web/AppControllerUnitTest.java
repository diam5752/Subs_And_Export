package com.ascentia.subs.web;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AppControllerUnitTest {

    @Test
    void sanitizesRequestedDownloadNameAndPreservesServedExtension() {
        assertThat(AppController.sanitizeDownloadFilename(
                "Ε Isous_subs.mp4",
                "processed_1080x1920.mp4"
        )).isEqualTo("Ε Isous_subs.mp4");
        assertThat(AppController.sanitizeDownloadFilename(
                "../../bad\r\nname.exe",
                "processed.srt"
        )).isEqualTo("bad__name.srt");
        assertThat(AppController.sanitizeDownloadFilename(null, "processed.vtt"))
                .isEqualTo("processed.vtt");
    }
}
