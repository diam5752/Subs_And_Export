package com.ascentia.subs;

import java.util.Map;
import java.util.Properties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SubsAndExportProjectApplicationUnitTest {

    @Test
    void productionStartupFailsBeforeLaunchingSpring() {
        boolean[] launched = {false};

        // REGRESSION: the Java migration surface could run Flyway and serve
        // production deletes without a restore-surviving erasure journal.
        assertThatThrownBy(() -> SubsAndExportProjectApplication.start(
                new String[0],
                Map.of("GSP_APP_ENV", "production"),
                new Properties(),
                () -> launched[0] = true
        ))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("restore-safe erasure journal parity");

        assertThat(launched[0]).isFalse();
    }

    @Test
    void productionIsTheFailClosedDefaultAndAnyUnsafeSignalRejects() {
        assertThatThrownBy(() -> SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of(),
                new Properties()
        )).isInstanceOf(IllegalStateException.class);

        assertThatThrownBy(() -> SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("GSP_APP_ENV", "production", "APP_ENV", "local"),
                new Properties()
        )).isInstanceOf(IllegalStateException.class);

        assertThatThrownBy(() -> SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--app.env=production"},
                Map.of("GSP_APP_ENV", "local"),
                new Properties()
        )).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void explicitDevelopmentAndLocalRuntimesRemainAvailable() {
        boolean[] launched = {false};
        Properties localSystemProperties = new Properties();
        localSystemProperties.setProperty("APP_ENV", "localhost");

        SubsAndExportProjectApplication.start(
                new String[0],
                Map.of("GSP_APP_ENV", "local"),
                new Properties(),
                () -> launched[0] = true
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("APP_ENV", "development"),
                new Properties()
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--ignored=value", "--app.env=dev"},
                Map.of(),
                new Properties()
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("GSP_APP_ENV", " "),
                localSystemProperties
        );

        assertThat(launched[0]).isTrue();
    }

    @Test
    void supportedCommandLineAndSystemPropertyAliasesPreserveDevelopmentStartup() {
        Properties gspSystemProperties = new Properties();
        gspSystemProperties.setProperty("GSP_APP_ENV", "local");
        gspSystemProperties.setProperty("APP_ENV", "development");
        Properties directSystemProperties = new Properties();
        directSystemProperties.setProperty("app.env", " LOCAL ");
        directSystemProperties.setProperty("GSP_APP_ENV", "dev");

        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--GSP_APP_ENV=development"},
                Map.of(),
                new Properties()
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--APP_ENV=localhost"},
                Map.of(),
                new Properties()
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--app.env= ", "--GSP_APP_ENV=dev"},
                Map.of("GSP_APP_ENV", "local"),
                new Properties()
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("GSP_APP_ENV", "development"),
                gspSystemProperties
        );
        SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("GSP_APP_ENV", "localhost"),
                directSystemProperties
        );
    }

    @Test
    void conflictingOrUnknownSignalsRejectBeforeLaunchingSpring() {
        boolean[] launched = {false};
        Properties conflictingProperties = new Properties();
        conflictingProperties.setProperty("app.env", "dev");
        conflictingProperties.setProperty("APP_ENV", "preview");

        // REGRESSION: a local CLI alias previously overrode the production
        // GSP_APP_ENV signal even though Spring could still bind production.
        assertThatThrownBy(() -> SubsAndExportProjectApplication.start(
                new String[] {"--APP_ENV=local"},
                Map.of("GSP_APP_ENV", "production"),
                new Properties(),
                () -> launched[0] = true
        )).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> SubsAndExportProjectApplication.requireSafeRuntime(
                new String[] {"--GSP_APP_ENV=dev", "--GSP_APP_ENV=production"},
                Map.of(),
                new Properties()
        )).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> SubsAndExportProjectApplication.requireSafeRuntime(
                new String[0],
                Map.of("APP_ENV", "local"),
                conflictingProperties
        )).isInstanceOf(IllegalStateException.class);

        assertThat(launched[0]).isFalse();
    }
}
