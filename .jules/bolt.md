# Bolt's Journal ⚡

## 2024-05-22 - ProcessContext Granularity
**Learning:** The `ProcessContext` combines high-frequency updates (`currentTime`) with static configuration and methods. This causes all consumers (like `Sidebar`) to re-render on every video frame, even if they don't use the time data.
**Action:** When using large contexts, wrap heavy consumer components' return values in `useMemo` (excluding the high-frequency values from dependencies) to isolate the DOM generation from the context updates.
