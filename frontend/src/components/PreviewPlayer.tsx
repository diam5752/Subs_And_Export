import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  forwardRef,
  memo,
} from "react";
import Image from "next/image";
import {
  SubtitleOverlay,
  type SubtitleTransformControls,
} from "./SubtitleOverlay";
import type {
  PreviewPlayerHandle,
  PreviewPlayerProps,
} from "./PreviewPlayerTypes";
import {
  clamp,
  FIRST_FRAME_PRIME_TIME_SECONDS,
  formatGestureTime,
  type PendingPlaybackCommand,
  type VideoWithFrameCallback,
} from "./previewPlayerSupport";
import { usePreviewGestures } from "./usePreviewGestures";
import { findCueIndexAtTime } from "@/lib/subtitleUtils";
import { BRAND } from "@/lib/brand";

export type {
  InlineSubtitleEditorConfig,
  PreviewPlayerHandle,
  SubtitleTransformConfig,
} from "./PreviewPlayerTypes";

export const PreviewPlayer = memo(
  forwardRef<PreviewPlayerHandle, PreviewPlayerProps>(
    (
      {
        videoUrl,
        cues,
        settings,
        onTimeUpdate,
        initialTime = 0,
        subtitleEditor,
        subtitleTransformControls,
        playbackToggleLabel = "Toggle video playback",
        onPlaybackStatusChange,
      },
      ref,
    ) => {
      const videoRef = useRef<HTMLVideoElement>(null);
      const containerRef = useRef<HTMLDivElement>(null);
      const [currentTime, setCurrentTime] = useState(initialTime);
      const [contentRect, setContentRect] = useState({
        width: 1080,
        height: 1920,
        top: 0,
        left: 0,
      });
      const rafIdRef = useRef<number | null>(null);
      const frameCallbackIdRef = useRef<number | null>(null);
      const frameCallbackVideoRef = useRef<VideoWithFrameCallback | null>(null);
      const isTimeSyncRunningRef = useRef(false);
      const playbackIntentRef = useRef<boolean | null>(null);
      const playbackRequestIdRef = useRef(0);
      const pendingPlaybackCommandRef = useRef<PendingPlaybackCommand | null>(
        null,
      );

      const reportPlaybackStatus = useCallback(() => {
        const video = videoRef.current;
        if (!video || !onPlaybackStatusChange) return;
        onPlaybackStatusChange({
          duration: Number.isFinite(video.duration) ? video.duration : 0,
          isPlaying: !video.paused && !video.ended,
          isMuted: video.muted,
        });
      }, [onPlaybackStatusChange]);

      const requestPlay = useCallback(
        (onRejected?: () => void) => {
          const video = videoRef.current;
          if (!video) return;

          const requestId = playbackRequestIdRef.current + 1;
          playbackRequestIdRef.current = requestId;
          playbackIntentRef.current = true;
          pendingPlaybackCommandRef.current = { id: requestId, kind: "play" };

          let playRequest: Promise<void>;
          try {
            playRequest = video.play();
          } catch {
            if (playbackRequestIdRef.current === requestId) {
              playbackIntentRef.current = false;
              pendingPlaybackCommandRef.current = null;
              onRejected?.();
              reportPlaybackStatus();
            }
            return;
          }

          void playRequest
            .then(() => {
              const pendingCommand = pendingPlaybackCommandRef.current;
              if (
                pendingCommand?.id === requestId &&
                pendingCommand.kind === "play"
              ) {
                pendingPlaybackCommandRef.current = null;
              }
            })
            .catch(() => {
              if (
                playbackRequestIdRef.current !== requestId ||
                playbackIntentRef.current !== true
              ) {
                return;
              }

              playbackIntentRef.current = false;
              pendingPlaybackCommandRef.current = null;
              onRejected?.();
              reportPlaybackStatus();
            });
        },
        [reportPlaybackStatus],
      );

      const requestPause = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        const previousCommand = pendingPlaybackCommandRef.current;
        const requestId = playbackRequestIdRef.current + 1;
        playbackRequestIdRef.current = requestId;
        playbackIntentRef.current = false;
        pendingPlaybackCommandRef.current = { id: requestId, kind: "pause" };
        const wasAlreadyPaused = video.paused;
        video.pause();
        if (
          wasAlreadyPaused &&
          previousCommand?.kind !== "play" &&
          pendingPlaybackCommandRef.current?.id === requestId
        ) {
          pendingPlaybackCommandRef.current = null;
        }
      }, []);

      const togglePlayback = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;

        const isPlayingOrRequested =
          playbackIntentRef.current ?? (!video.paused && !video.ended);
        if (!isPlayingOrRequested) {
          if (video.ended) {
            video.currentTime = 0;
            setCurrentTime(0);
          }
          requestPlay();
          return;
        }

        requestPause();
      }, [requestPause, requestPlay]);

      const toggleMuted = useCallback(() => {
        const video = videoRef.current;
        if (!video) return;
        video.muted = !video.muted;
        reportPlaybackStatus();
      }, [reportPlaybackStatus]);

      const {
        gestureFeedback,
        subtitleGestureResetToken,
        pauseForSubtitleInteraction,
        hasActiveTransformCue,
        handlePreviewPointerDown,
        handlePreviewPointerMove,
        finishPreviewGesture,
        handleStagePointerDownCapture,
        handleStagePointerMoveCapture,
        finishStagePointer,
        handleStageLostPointerCapture,
        handleStageClickCapture,
      } = usePreviewGestures({
        videoRef,
        containerRef,
        cues,
        currentTime,
        fontSize: settings.fontSize,
        subtitleTransformControls,
        onTimeUpdate,
        setCurrentTime,
        playbackIntentRef,
        requestPlay,
        requestPause,
        togglePlayback,
        reportPlaybackStatus,
      });

      useEffect(
        () => () => {
          playbackRequestIdRef.current += 1;
          playbackIntentRef.current = null;
          pendingPlaybackCommandRef.current = null;
        },
        [],
      );

      useEffect(() => {
        playbackRequestIdRef.current += 1;
        playbackIntentRef.current = null;
        pendingPlaybackCommandRef.current = null;
      }, [videoUrl]);

      useImperativeHandle(
        ref,
        () => ({
          seekTo: (time: number) => {
            if (videoRef.current) {
              videoRef.current.currentTime = time;
              setCurrentTime(time);
            }
          },
          pause: () => {
            if (!videoRef.current) return;
            requestPause();
            setCurrentTime(videoRef.current.currentTime);
          },
          togglePlayback,
          toggleMuted,
        }),
        [requestPause, toggleMuted, togglePlayback],
      );

      const editableCues = subtitleEditor?.cues;
      const activeEditableCueIndex = useMemo(() => {
        if (!editableCues?.length) return -1;
        return findCueIndexAtTime(editableCues, currentTime);
      }, [currentTime, editableCues]);

      const inlineEditor = useMemo(() => {
        if (!subtitleEditor || activeEditableCueIndex < 0) return undefined;
        if (
          subtitleEditor.editingCueIndex !== null &&
          subtitleEditor.editingCueIndex !== activeEditableCueIndex
        ) {
          return undefined;
        }

        return {
          cueIndex: activeEditableCueIndex,
          isEditing: subtitleEditor.editingCueIndex === activeEditableCueIndex,
          draftText: subtitleEditor.draftText,
          isSaving: subtitleEditor.isSaving,
          error: subtitleEditor.error,
          autoFocus: subtitleEditor.autoFocus,
          labels: subtitleEditor.labels,
          onBeginEdit: () => {
            pauseForSubtitleInteraction();
            subtitleEditor.onBeginEdit(activeEditableCueIndex);
          },
          onChange: subtitleEditor.onChange,
          onSave: subtitleEditor.onSave,
          onCancel: subtitleEditor.onCancel,
        };
      }, [activeEditableCueIndex, pauseForSubtitleInteraction, subtitleEditor]);

      const overlayTransformControls = useMemo<
        SubtitleTransformControls | undefined
      >(() => {
        if (!subtitleTransformControls) return undefined;
        return {
          ...subtitleTransformControls,
          onInteractionStart: pauseForSubtitleInteraction,
        };
      }, [pauseForSubtitleInteraction, subtitleTransformControls]);

      // Handle time update from video
      const handleTimeUpdate = () => {
        if (videoRef.current) {
          if (onTimeUpdate) onTimeUpdate(videoRef.current.currentTime);
        }
      };

      const stopHighResTimeSync = useCallback(() => {
        const video =
          frameCallbackVideoRef.current ??
          (videoRef.current as VideoWithFrameCallback | null);

        if (
          frameCallbackIdRef.current !== null &&
          video?.cancelVideoFrameCallback
        ) {
          video.cancelVideoFrameCallback(frameCallbackIdRef.current);
        }
        frameCallbackIdRef.current = null;
        frameCallbackVideoRef.current = null;

        if (rafIdRef.current !== null) {
          cancelAnimationFrame(rafIdRef.current);
        }
        rafIdRef.current = null;
        isTimeSyncRunningRef.current = false;
      }, []);

      const startHighResTimeSync = useCallback(() => {
        const video = videoRef.current as VideoWithFrameCallback | null;
        if (!video || isTimeSyncRunningRef.current) return;
        isTimeSyncRunningRef.current = true;
        frameCallbackVideoRef.current = video;

        const sync = () => {
          const currentVideo =
            videoRef.current as VideoWithFrameCallback | null;
          if (!currentVideo) {
            stopHighResTimeSync();
            return;
          }

          setCurrentTime(currentVideo.currentTime);

          if (currentVideo.paused || currentVideo.ended) {
            stopHighResTimeSync();
            return;
          }

          if (currentVideo.requestVideoFrameCallback) {
            frameCallbackIdRef.current = currentVideo.requestVideoFrameCallback(
              () => sync(),
            );
          } else {
            rafIdRef.current = requestAnimationFrame(sync);
          }
        };

        if (video.requestVideoFrameCallback) {
          frameCallbackIdRef.current = video.requestVideoFrameCallback(() =>
            sync(),
          );
        } else {
          rafIdRef.current = requestAnimationFrame(sync);
        }
      }, [stopHighResTimeSync]);

      // Calculate actual video position within the container (object-contain logic)
      const updateContentRect = useCallback(() => {
        if (!videoRef.current || !containerRef.current) return;

        const video = videoRef.current;
        const container = containerRef.current;

        const vW = video.videoWidth || 1080;
        const vH = video.videoHeight || 1920;
        const cW = container.clientWidth;
        const cH = container.clientHeight;

        if (vW === 0 || vH === 0) return;

        const videoAspect = vW / vH;
        const containerAspect = cW / cH;

        let renderW, renderH, renderTop, renderLeft;

        // Container is WIDER than video (Pillarbox)
        if (containerAspect > videoAspect) {
          renderH = cH;
          renderW = cH * videoAspect;
          renderTop = 0;
          renderLeft = (cW - renderW) / 2;
        }
        // Container is TALLER than video (Letterbox)
        else {
          renderW = cW;
          renderH = cW / videoAspect;
          renderLeft = 0;
          renderTop = (cH - renderH) / 2;
        }

        setContentRect({
          width: renderW,
          height: renderH,
          top: renderTop,
          left: renderLeft,
        });
      }, []);

      useEffect(() => {
        const observer = new ResizeObserver(updateContentRect);
        if (containerRef.current) observer.observe(containerRef.current);
        window.addEventListener("resize", updateContentRect);

        return () => {
          observer.disconnect();
          window.removeEventListener("resize", updateContentRect);
        };
      }, [updateContentRect]);

      // Set initial time when video loads or initialTime changes
      useEffect(() => {
        if (typeof initialTime === "number" && videoRef.current) {
          if (Math.abs(videoRef.current.currentTime - initialTime) > 0.01) {
            videoRef.current.currentTime = initialTime;
          }
        }
      }, [initialTime]);

      useEffect(() => {
        const video = videoRef.current as VideoWithFrameCallback | null;
        if (!video) return;

        const handlePlay = () => {
          const pendingCommand = pendingPlaybackCommandRef.current;
          if (
            playbackIntentRef.current === false &&
            pendingCommand?.kind === "pause"
          ) {
            // A queued play event from an older request lost the race to a
            // newer pause command. Keep the latest user intent authoritative.
            video.pause();
            return;
          }

          playbackIntentRef.current = true;
          if (pendingCommand?.kind === "play") {
            pendingPlaybackCommandRef.current = null;
          }
          startHighResTimeSync();
          reportPlaybackStatus();
        };
        const handlePause = () => {
          const pendingCommand = pendingPlaybackCommandRef.current;
          if (
            playbackIntentRef.current === true &&
            pendingCommand?.kind === "play"
          ) {
            // A delayed pause event from the previous command must not
            // overwrite a newer play request that is still settling.
            return;
          }

          playbackRequestIdRef.current += 1;
          playbackIntentRef.current = false;
          pendingPlaybackCommandRef.current = null;
          setCurrentTime(video.currentTime);
          stopHighResTimeSync();
          reportPlaybackStatus();
        };
        const handleSeeked = () => setCurrentTime(video.currentTime);
        const handleEnded = () => {
          playbackRequestIdRef.current += 1;
          playbackIntentRef.current = false;
          pendingPlaybackCommandRef.current = null;
          setCurrentTime(video.currentTime);
          stopHighResTimeSync();
          reportPlaybackStatus();
        };
        const handleDurationChange = () => reportPlaybackStatus();
        const handleVolumeChange = () => reportPlaybackStatus();

        video.addEventListener("play", handlePlay);
        video.addEventListener("pause", handlePause);
        video.addEventListener("seeked", handleSeeked);
        video.addEventListener("ended", handleEnded);
        video.addEventListener("durationchange", handleDurationChange);
        video.addEventListener("volumechange", handleVolumeChange);

        if (!video.paused && !video.ended) startHighResTimeSync();
        reportPlaybackStatus();

        return () => {
          stopHighResTimeSync();
          video.removeEventListener("play", handlePlay);
          video.removeEventListener("pause", handlePause);
          video.removeEventListener("seeked", handleSeeked);
          video.removeEventListener("ended", handleEnded);
          video.removeEventListener("durationchange", handleDurationChange);
          video.removeEventListener("volumechange", handleVolumeChange);
        };
      }, [reportPlaybackStatus, startHighResTimeSync, stopHighResTimeSync]);

      // OPTIMIZATION: Removed redundant re-segmentation logic.
      // The cues passed to PreviewPlayer are expected to be already processed/segmented
      // by the parent (ProcessContext). This saves a duplicate canvas text measurement loop.
      const seekProgress =
        gestureFeedback?.kind === "seek" && gestureFeedback.duration > 0
          ? clamp(
              (gestureFeedback.currentTime / gestureFeedback.duration) * 100,
              0,
              100,
            )
          : 0;

      return (
        <div
          ref={containerRef}
          className="preview-gesture-surface relative w-full h-full bg-black rounded-xl overflow-hidden shadow-lg border border-white/10"
          data-subtitle-pinch-enabled={
            subtitleTransformControls && hasActiveTransformCue
              ? "true"
              : "false"
          }
          onPointerDownCapture={handleStagePointerDownCapture}
          onPointerMoveCapture={handleStagePointerMoveCapture}
          onPointerUpCapture={(event) => finishStagePointer(event, false)}
          onPointerCancelCapture={(event) => finishStagePointer(event, true)}
          onLostPointerCapture={handleStageLostPointerCapture}
          onClickCapture={handleStageClickCapture}
        >
          <video
            ref={videoRef}
            src={videoUrl}
            className="preview-video h-full w-full cursor-pointer object-contain"
            playsInline
            preload="metadata"
            draggable={false}
            disablePictureInPicture
            disableRemotePlayback
            controlsList="nodownload noplaybackrate noremoteplayback"
            role="button"
            tabIndex={0}
            aria-label={playbackToggleLabel}
            onPointerDown={handlePreviewPointerDown}
            onPointerMove={handlePreviewPointerMove}
            onPointerUp={(event) => finishPreviewGesture(event)}
            onPointerCancel={(event) => finishPreviewGesture(event, true)}
            onContextMenu={(event) => event.preventDefault()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                togglePlayback();
              }
            }}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={() => {
              updateContentRect();
              if (typeof initialTime === "number" && videoRef.current) {
                const video = videoRef.current;
                const shouldPrimeFirstFrame =
                  initialTime <= 0 &&
                  video.paused &&
                  video.currentTime === 0 &&
                  Number.isFinite(video.duration) &&
                  video.duration > 0;

                if (shouldPrimeFirstFrame) {
                  // WebKit only fetches metadata for a paused video at 0:00.
                  // A tiny seek requests and paints the first frame without
                  // autoplaying or preloading the complete media file.
                  video.currentTime = Math.min(
                    FIRST_FRAME_PRIME_TIME_SECONDS,
                    video.duration / 2,
                  );
                } else if (Math.abs(video.currentTime - initialTime) > 0.01) {
                  video.currentTime = initialTime;
                }
                setCurrentTime(video.currentTime);
              }
              reportPlaybackStatus();
            }}
          />

          {gestureFeedback?.kind === "speed" && (
            <div
              className="preview-gesture-feedback"
              data-kind="speed"
              data-testid="preview-gesture-feedback"
              role="status"
              aria-live="polite"
            >
              2×
            </div>
          )}

          {gestureFeedback?.kind === "seek" && (
            <div
              className="preview-seek-feedback"
              data-progress={Math.round(seekProgress)}
              data-testid="preview-gesture-feedback"
              role="status"
              aria-live="polite"
            >
              <div className="preview-seek-feedback-copy">
                <strong>
                  {gestureFeedback.delta >= 0 ? "+" : "−"}
                  {formatGestureTime(Math.abs(gestureFeedback.delta))}
                </strong>
                <span>
                  {formatGestureTime(gestureFeedback.currentTime)}
                  {" / "}
                  {formatGestureTime(gestureFeedback.duration)}
                </span>
                <span>
                  −
                  {formatGestureTime(
                    Math.max(
                      0,
                      gestureFeedback.duration - gestureFeedback.currentTime,
                    ),
                  )}
                </span>
              </div>
              <div className="preview-seek-track" aria-hidden="true">
                <span
                  className="preview-seek-progress"
                  data-testid="preview-seek-progress"
                  style={{ width: `${seekProgress}%` }}
                />
                <span
                  className="preview-seek-thumb"
                  style={{ left: `${seekProgress}%` }}
                />
              </div>
            </div>
          )}

          <div
            style={{
              position: "absolute",
              top: contentRect.top,
              left: contentRect.left,
              width: contentRect.width,
              height: contentRect.height,
              pointerEvents: "none",
            }}
          >
            {/* Watermark Overlay */}
            {settings.watermarkEnabled && (
              <div className="absolute bottom-[40px] right-[40px] z-20 w-[30%] animate-in fade-in duration-500">
                <Image
                  src={BRAND.assets.watermark}
                  alt="gsubs watermark"
                  width={1360}
                  height={304}
                  sizes="20vw"
                  className="w-full h-auto opacity-90"
                />
              </div>
            )}

            <SubtitleOverlay
              currentTime={currentTime}
              cues={cues}
              settings={settings}
              videoWidth={contentRect.width}
              videoHeight={contentRect.height}
              inlineEditor={inlineEditor}
              transformControls={overlayTransformControls}
              gestureResetToken={subtitleGestureResetToken}
            />
          </div>
        </div>
      );
    },
  ),
);

PreviewPlayer.displayName = "PreviewPlayer";
