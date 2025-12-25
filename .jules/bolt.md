## 2024-05-23 - [ProcessProvider Optimization]
**Learning:** React Context Providers with large, un-memoized value objects are a silent performance killer. In `ProcessContext`, the value object was being recreated on every render, causing all consumers (Sidebar, ProcessView, etc.) to re-render even if the relevant data hadn't changed.
**Action:** Always wrap Context Provider values in `useMemo`. For contexts with frequently changing data (like progress), consider splitting the context into State (frequent updates) and Actions (stable references) to further isolate re-renders.
