package com.ascentia.subs.config;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private String env = "production";
    private String databaseUrl = "postgresql://localhost:5432/gsp_dev";
    private String databaseUsername = "";
    private String databasePassword = "";
    private String allowedOrigins = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080";
    private String trustedHosts = "localhost,127.0.0.1,0.0.0.0,[::1],testserver";
    private String proxyTrustedHosts = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16";
    private boolean forceHttps;
    private int maxUploadMb = 1024;
    private int maxVideoDurationSeconds = 210;
    private int maxConcurrentJobs = 2;
    private int staticRateLimit = 60;
    private int staticRateLimitWindow = 60;
    private int signupLimitPerIpPerDay = 5;
    private int defaultWidth = 1080;
    private int defaultHeight = 1920;
    private int maxResolutionDimension = 4096;
    private String defaultTranscribeTier = "standard";
    private String socialLlmModel = "gpt-5.1-mini";
    private String factcheckLlmModel = "gpt-5.1-mini";
    private String extractionLlmModel = "gpt-5.1-mini";
    private boolean useLlmByDefault;
    private String llmModel = "gpt-5.1-mini";
    private double llmTemperature = 0.6d;
    private Map<String, String> transcribeTierProvider = Map.of("standard", "groq", "pro", "groq");
    private Map<String, String> transcribeTierModel = Map.of("standard", "whisper-large-v3-turbo", "pro", "whisper-large-v3");
    private Map<String, Integer> creditsPerMinuteTranscribe = Map.of("standard", 10, "pro", 20);
    private Map<String, Integer> creditsMinTranscribe = Map.of("standard", 25, "pro", 50);
    private Map<String, Integer> creditsMinSocialCopy = Map.of("standard", 10, "pro", 20);
    private Map<String, Integer> creditsMinFactCheck = Map.of("standard", 20, "pro", 40);
    private String gcsBucket = "";
    private String gcsUploadsPrefix = "uploads";
    private String gcsStaticPrefix = "static";
    private int gcsUploadUrlTtlSeconds = 3600;
    private int gcsDownloadUrlTtlSeconds = 600;
    private boolean gcsKeepUploads = true;
    private String gcsSignerEmail = "";
    private String adminEmails = "";

    public String env() {
        return env;
    }

    public boolean isDev() {
        return "dev".equalsIgnoreCase(env) || "development".equalsIgnoreCase(env) || "local".equalsIgnoreCase(env);
    }

    public String databaseUrl() {
        return databaseUrl;
    }

    public String databaseUsername() {
        return databaseUsername;
    }

    public String databasePassword() {
        return databasePassword;
    }

    public List<String> allowedOriginsList() {
        return csvToList(allowedOrigins);
    }

    public List<String> trustedHostsList() {
        return csvToList(trustedHosts);
    }

    public List<String> proxyTrustedHostsList() {
        return csvToList(proxyTrustedHosts);
    }

    public Path dataDir() {
        return Path.of("data");
    }

    public Path watermarkPath() {
        return Path.of("Ascentia_Logo.png");
    }

    public static List<String> csvToList(String raw) {
        return Stream.ofNullable(raw)
                .flatMap(value -> Stream.of(value.split(",")))
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .toList();
    }

    public String getEnv() {
        return env;
    }

    public void setEnv(String env) {
        this.env = env;
    }

    public String getDatabaseUrl() {
        return databaseUrl;
    }

    public void setDatabaseUrl(String databaseUrl) {
        this.databaseUrl = databaseUrl;
    }

    public String getDatabaseUsername() {
        return databaseUsername;
    }

    public void setDatabaseUsername(String databaseUsername) {
        this.databaseUsername = databaseUsername;
    }

    public String getDatabasePassword() {
        return databasePassword;
    }

    public void setDatabasePassword(String databasePassword) {
        this.databasePassword = databasePassword;
    }

    public String getAllowedOrigins() {
        return allowedOrigins;
    }

    public void setAllowedOrigins(String allowedOrigins) {
        this.allowedOrigins = allowedOrigins;
    }

    public String getTrustedHosts() {
        return trustedHosts;
    }

    public void setTrustedHosts(String trustedHosts) {
        this.trustedHosts = trustedHosts;
    }

    public String getProxyTrustedHosts() {
        return proxyTrustedHosts;
    }

    public void setProxyTrustedHosts(String proxyTrustedHosts) {
        this.proxyTrustedHosts = proxyTrustedHosts;
    }

    public boolean isForceHttps() {
        return forceHttps;
    }

    public void setForceHttps(boolean forceHttps) {
        this.forceHttps = forceHttps;
    }

    public int getMaxUploadMb() {
        return maxUploadMb;
    }

    public void setMaxUploadMb(int maxUploadMb) {
        this.maxUploadMb = maxUploadMb;
    }

    public int getMaxVideoDurationSeconds() {
        return maxVideoDurationSeconds;
    }

    public void setMaxVideoDurationSeconds(int maxVideoDurationSeconds) {
        this.maxVideoDurationSeconds = maxVideoDurationSeconds;
    }

    public int getMaxConcurrentJobs() {
        return maxConcurrentJobs;
    }

    public void setMaxConcurrentJobs(int maxConcurrentJobs) {
        this.maxConcurrentJobs = maxConcurrentJobs;
    }

    public int getStaticRateLimit() {
        return staticRateLimit;
    }

    public void setStaticRateLimit(int staticRateLimit) {
        this.staticRateLimit = staticRateLimit;
    }

    public int getStaticRateLimitWindow() {
        return staticRateLimitWindow;
    }

    public void setStaticRateLimitWindow(int staticRateLimitWindow) {
        this.staticRateLimitWindow = staticRateLimitWindow;
    }

    public int getSignupLimitPerIpPerDay() {
        return signupLimitPerIpPerDay;
    }

    public void setSignupLimitPerIpPerDay(int signupLimitPerIpPerDay) {
        this.signupLimitPerIpPerDay = signupLimitPerIpPerDay;
    }

    public int getDefaultWidth() {
        return defaultWidth;
    }

    public void setDefaultWidth(int defaultWidth) {
        this.defaultWidth = defaultWidth;
    }

    public int getDefaultHeight() {
        return defaultHeight;
    }

    public void setDefaultHeight(int defaultHeight) {
        this.defaultHeight = defaultHeight;
    }

    public int getMaxResolutionDimension() {
        return maxResolutionDimension;
    }

    public void setMaxResolutionDimension(int maxResolutionDimension) {
        this.maxResolutionDimension = maxResolutionDimension;
    }

    public String getDefaultTranscribeTier() {
        return defaultTranscribeTier;
    }

    public void setDefaultTranscribeTier(String defaultTranscribeTier) {
        this.defaultTranscribeTier = defaultTranscribeTier;
    }

    public String getSocialLlmModel() {
        return socialLlmModel;
    }

    public void setSocialLlmModel(String socialLlmModel) {
        this.socialLlmModel = socialLlmModel;
    }

    public String getFactcheckLlmModel() {
        return factcheckLlmModel;
    }

    public void setFactcheckLlmModel(String factcheckLlmModel) {
        this.factcheckLlmModel = factcheckLlmModel;
    }

    public String getExtractionLlmModel() {
        return extractionLlmModel;
    }

    public void setExtractionLlmModel(String extractionLlmModel) {
        this.extractionLlmModel = extractionLlmModel;
    }

    public boolean isUseLlmByDefault() {
        return useLlmByDefault;
    }

    public void setUseLlmByDefault(boolean useLlmByDefault) {
        this.useLlmByDefault = useLlmByDefault;
    }

    public String getLlmModel() {
        return llmModel;
    }

    public void setLlmModel(String llmModel) {
        this.llmModel = llmModel;
    }

    public double getLlmTemperature() {
        return llmTemperature;
    }

    public void setLlmTemperature(double llmTemperature) {
        this.llmTemperature = llmTemperature;
    }

    public Map<String, String> getTranscribeTierProvider() {
        return transcribeTierProvider;
    }

    public void setTranscribeTierProvider(Map<String, String> transcribeTierProvider) {
        this.transcribeTierProvider = transcribeTierProvider;
    }

    public Map<String, String> getTranscribeTierModel() {
        return transcribeTierModel;
    }

    public void setTranscribeTierModel(Map<String, String> transcribeTierModel) {
        this.transcribeTierModel = transcribeTierModel;
    }

    public Map<String, Integer> getCreditsPerMinuteTranscribe() {
        return creditsPerMinuteTranscribe;
    }

    public void setCreditsPerMinuteTranscribe(Map<String, Integer> creditsPerMinuteTranscribe) {
        this.creditsPerMinuteTranscribe = creditsPerMinuteTranscribe;
    }

    public Map<String, Integer> getCreditsMinTranscribe() {
        return creditsMinTranscribe;
    }

    public void setCreditsMinTranscribe(Map<String, Integer> creditsMinTranscribe) {
        this.creditsMinTranscribe = creditsMinTranscribe;
    }

    public Map<String, Integer> getCreditsMinSocialCopy() {
        return creditsMinSocialCopy;
    }

    public void setCreditsMinSocialCopy(Map<String, Integer> creditsMinSocialCopy) {
        this.creditsMinSocialCopy = creditsMinSocialCopy;
    }

    public Map<String, Integer> getCreditsMinFactCheck() {
        return creditsMinFactCheck;
    }

    public void setCreditsMinFactCheck(Map<String, Integer> creditsMinFactCheck) {
        this.creditsMinFactCheck = creditsMinFactCheck;
    }

    public String getGcsBucket() {
        return gcsBucket;
    }

    public void setGcsBucket(String gcsBucket) {
        this.gcsBucket = gcsBucket;
    }

    public String getGcsUploadsPrefix() {
        return gcsUploadsPrefix;
    }

    public void setGcsUploadsPrefix(String gcsUploadsPrefix) {
        this.gcsUploadsPrefix = gcsUploadsPrefix;
    }

    public String getGcsStaticPrefix() {
        return gcsStaticPrefix;
    }

    public void setGcsStaticPrefix(String gcsStaticPrefix) {
        this.gcsStaticPrefix = gcsStaticPrefix;
    }

    public int getGcsUploadUrlTtlSeconds() {
        return gcsUploadUrlTtlSeconds;
    }

    public void setGcsUploadUrlTtlSeconds(int gcsUploadUrlTtlSeconds) {
        this.gcsUploadUrlTtlSeconds = gcsUploadUrlTtlSeconds;
    }

    public int getGcsDownloadUrlTtlSeconds() {
        return gcsDownloadUrlTtlSeconds;
    }

    public void setGcsDownloadUrlTtlSeconds(int gcsDownloadUrlTtlSeconds) {
        this.gcsDownloadUrlTtlSeconds = gcsDownloadUrlTtlSeconds;
    }

    public boolean isGcsKeepUploads() {
        return gcsKeepUploads;
    }

    public void setGcsKeepUploads(boolean gcsKeepUploads) {
        this.gcsKeepUploads = gcsKeepUploads;
    }

    public String getGcsSignerEmail() {
        return gcsSignerEmail;
    }

    public void setGcsSignerEmail(String gcsSignerEmail) {
        this.gcsSignerEmail = gcsSignerEmail;
    }

    public String getAdminEmails() {
        return adminEmails;
    }

    public void setAdminEmails(String adminEmails) {
        this.adminEmails = adminEmails;
    }
}
