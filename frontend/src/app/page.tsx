'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';

export default function DashboardPage() {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState('');

  // Processing settings
  const [showSettings, setShowSettings] = useState(false);
  const [transcribeMode, setTranscribeMode] = useState<'fast' | 'balanced' | 'turbo' | 'best'>('turbo');
  const [outputQuality, setOutputQuality] = useState<'low size' | 'balanced' | 'high quality'>('balanced');
  const [useAI, setUseAI] = useState(false);
  const [contextPrompt, setContextPrompt] = useState('');

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  // Poll job status
  useEffect(() => {
    if (!jobId) return;

    const pollInterval = setInterval(async () => {
      try {
        const job = await api.getJobStatus(jobId);
        setProgress(job.progress);
        setStatusMessage(job.message || '');

        if (job.status === 'completed' || job.status === 'failed') {
          clearInterval(pollInterval);
          setIsProcessing(false);
          if (job.status === 'failed') {
            setError(job.message || 'Processing failed');
          }
        }
      } catch {
        clearInterval(pollInterval);
        setIsProcessing(false);
        setError('Failed to check job status');
      }
    }, 1000);

    return () => clearInterval(pollInterval);
  }, [jobId]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError('');
    }
  };

  const handleProcess = async () => {
    if (!selectedFile) return;

    setIsProcessing(true);
    setError('');
    setProgress(0);
    setStatusMessage('Uploading...');

    // Map transcribe mode to model size
    const modelMap: Record<string, string> = {
      fast: 'tiny',
      balanced: 'medium',
      turbo: 'large-v3-turbo',
      best: 'large-v3'
    };

    try {
      const result = await api.processVideo(selectedFile, {
        transcribe_model: modelMap[transcribeMode],
        video_quality: outputQuality,
        use_llm: useAI,
        context_prompt: contextPrompt
      });
      setJobId(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start processing');
      setIsProcessing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--muted)]">Loading...</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen">
      {/* Navigation */}
      <nav className="border-b border-[var(--border)] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🎬</span>
            <span className="text-xl font-semibold">Greek Sub Publisher</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[var(--muted)]">{user.name}</span>
            <button onClick={logout} className="btn-secondary text-sm py-2 px-4">
              Sign Out
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-4">Video Processing Studio</h1>
          <p className="text-[var(--muted)] text-lg">
            Upload your video and we&apos;ll add professional Greek subtitles with AI
          </p>
        </div>

        {/* Upload Area */}
        <div
          className="card text-center cursor-pointer hover:border-[var(--accent)] transition-colors"
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="video/mp4,video/quicktime,video/x-matroska"
            onChange={handleFileSelect}
            className="hidden"
          />

          {selectedFile ? (
            <div className="py-8">
              <div className="text-6xl mb-4">🎥</div>
              <p className="text-xl font-medium">{selectedFile.name}</p>
              <p className="text-[var(--muted)] mt-2">
                {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            </div>
          ) : (
            <div className="py-12">
              <div className="text-6xl mb-4 opacity-50">📤</div>
              <p className="text-xl font-medium mb-2">Drop your video here</p>
              <p className="text-[var(--muted)]">or click to browse</p>
              <p className="text-sm text-[var(--muted)] mt-4">
                Supports MP4, MOV, MKV
              </p>
            </div>
          )}
        </div>

        {/* Processing Settings - Show when file is selected */}
        {selectedFile && !isProcessing && progress < 100 && (
          <div className="mt-6 card">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="w-full flex items-center justify-between text-left"
            >
              <span className="font-medium flex items-center gap-2">
                <span>⚙️</span> Processing Settings
              </span>
              <span className="text-[var(--muted)]">{showSettings ? '▲' : '▼'}</span>
            </button>

            {showSettings && (
              <div className="mt-4 space-y-5 pt-4 border-t border-[var(--border)]">
                {/* Transcription Mode */}
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    Speed / Accuracy
                  </label>
                  <div className="grid grid-cols-4 gap-2">
                    {(['fast', 'balanced', 'turbo', 'best'] as const).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setTranscribeMode(mode)}
                        className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${transcribeMode === mode
                            ? 'bg-[var(--accent)] text-white'
                            : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                          }`}
                      >
                        {mode.charAt(0).toUpperCase() + mode.slice(1)}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-1">
                    Turbo provides the best balance of speed and accuracy
                  </p>
                </div>

                {/* Output Quality */}
                <div>
                  <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                    Output Quality
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['low size', 'balanced', 'high quality'] as const).map((quality) => (
                      <button
                        key={quality}
                        onClick={() => setOutputQuality(quality)}
                        className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${outputQuality === quality
                            ? 'bg-[var(--accent)] text-white'
                            : 'bg-[var(--surface-elevated)] text-[var(--muted)] hover:text-[var(--foreground)]'
                          }`}
                      >
                        {quality.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                      </button>
                    ))}
                  </div>
                </div>

                {/* AI Features */}
                <div>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <div
                      onClick={() => setUseAI(!useAI)}
                      className={`w-11 h-6 rounded-full transition-colors relative ${useAI ? 'bg-[var(--accent)]' : 'bg-[var(--surface-elevated)]'
                        }`}
                    >
                      <div
                        className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${useAI ? 'translate-x-6' : 'translate-x-1'
                          }`}
                      />
                    </div>
                    <span className="font-medium">AI Viral Intelligence</span>
                  </label>
                  <p className="text-xs text-[var(--muted)] mt-1 ml-14">
                    Generate viral titles and descriptions using GPT-4
                  </p>
                </div>

                {/* Context Hints - Only show when AI is enabled */}
                {useAI && (
                  <div>
                    <label className="block text-sm font-medium text-[var(--muted)] mb-2">
                      Context Hints
                    </label>
                    <textarea
                      value={contextPrompt}
                      onChange={(e) => setContextPrompt(e.target.value)}
                      placeholder="Names, specific terms, topics..."
                      className="input-field h-20 resize-none"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Progress */}
        {isProcessing && (
          <div className="mt-8 card">
            <div className="flex items-center justify-between mb-3">
              <span className="font-medium">{statusMessage}</span>
              <span className="text-[var(--accent)]">{progress}%</span>
            </div>
            <div className="w-full bg-[var(--surface-elevated)] rounded-full h-2">
              <div
                className="bg-[var(--accent)] h-2 rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-8 bg-[var(--danger)]/10 border border-[var(--danger)]/30 text-[var(--danger)] px-6 py-4 rounded-xl">
            {error}
          </div>
        )}

        {/* Process Button */}
        {selectedFile && !isProcessing && progress < 100 && (
          <div className="mt-8 text-center">
            <button onClick={handleProcess} className="btn-primary text-lg px-8 py-4">
              ✨ Start Magic Processing
            </button>
          </div>
        )}

        {/* Success */}
        {progress === 100 && !isProcessing && (
          <div className="mt-8 card text-center bg-[var(--accent-secondary)]/10 border-[var(--accent-secondary)]/30">
            <div className="text-5xl mb-4">🎉</div>
            <h3 className="text-2xl font-bold mb-2">Processing Complete!</h3>
            <p className="text-[var(--muted)]">Your video is ready with Greek subtitles</p>
            <button
              onClick={() => {
                setSelectedFile(null);
                setProgress(0);
                setJobId(null);
              }}
              className="btn-primary mt-6"
            >
              Process Another Video
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
