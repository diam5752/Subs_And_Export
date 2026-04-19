package com.ascentia.subs;

import com.ascentia.subs.config.AppProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.modulith.Modulith;
import org.springframework.scheduling.annotation.EnableAsync;

@Modulith
@EnableAsync
@SpringBootApplication
@EnableConfigurationProperties(AppProperties.class)
public class SubsAndExportProjectApplication {

    public static void main(String[] args) {
        SpringApplication.run(SubsAndExportProjectApplication.class, args);
    }
}
