package com.ascentia.subs;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

import com.ascentia.subs.config.AppProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.modulith.Modulith;
import org.springframework.scheduling.annotation.EnableAsync;

@Modulith
@EnableAsync
@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@EnableConfigurationProperties(AppProperties.class)
public class SubsAndExportProjectApplication {

    private static final Set<String> SAFE_LOCAL_RUNTIMES = Set.of(
            "dev",
            "development",
            "local",
            "localhost"
    );
    private static final List<String> RUNTIME_PROPERTY_KEYS = List.of(
            "app.env",
            "GSP_APP_ENV",
            "APP_ENV"
    );

    public static void main(String[] args) {
        start(
                args,
                System.getenv(),
                System.getProperties(),
                () -> SpringApplication.run(SubsAndExportProjectApplication.class, args)
        );
    }

    static void start(
            String[] args,
            Map<String, String> environment,
            Properties systemProperties,
            Runnable launcher
    ) {
        requireSafeRuntime(args, environment, systemProperties);
        launcher.run();
    }

    static void requireSafeRuntime(
            String[] args,
            Map<String, String> environment,
            Properties systemProperties
    ) {
        List<String> runtimes = runtimeSignals(args, environment, systemProperties);
        boolean allSignalsAreSafe = !runtimes.isEmpty()
                && runtimes.stream().allMatch(SAFE_LOCAL_RUNTIMES::contains);
        if (!allSignalsAreSafe) {
            throw new IllegalStateException(
                    "Java production startup is disabled until restore-safe erasure journal parity is implemented."
            );
        }
    }

    private static List<String> runtimeSignals(
            String[] args,
            Map<String, String> environment,
            Properties systemProperties
    ) {
        List<String> runtimes = new ArrayList<>();
        for (String argument : args) {
            for (String key : RUNTIME_PROPERTY_KEYS) {
                addCommandLineSignal(runtimes, argument, key);
            }
        }
        for (String key : RUNTIME_PROPERTY_KEYS) {
            addRuntimeSignal(runtimes, systemProperties.getProperty(key));
        }
        addRuntimeSignal(runtimes, environment.get("GSP_APP_ENV"));
        addRuntimeSignal(runtimes, environment.get("APP_ENV"));
        return List.copyOf(runtimes);
    }

    private static void addCommandLineSignal(
            List<String> runtimes,
            String argument,
            String key
    ) {
        String prefix = "--" + key + "=";
        if (argument.startsWith(prefix)) {
            addRuntimeSignal(runtimes, argument.substring(prefix.length()));
        }
    }

    private static void addRuntimeSignal(List<String> runtimes, String candidate) {
        if (candidate != null && !candidate.isBlank()) {
            runtimes.add(candidate.strip().toLowerCase(Locale.ROOT));
        }
    }
}
