import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RecentJobsList } from "../RecentJobsList";
import { api } from "@/lib/api";
import type { JobResponse } from "@/lib/api";

let mockMissingTranslations = false;

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({
    t: (key: string) => {
      if (mockMissingTranslations) {
        return "";
      }
      if (key === "paginationShowing") {
        return "Showing {start}-{end} of {total}";
      }
      return key;
    },
  }),
}));

jest.mock("@/lib/api", () => ({
  api: {
    deleteJob: jest.fn(),
    deleteJobs: jest.fn(),
    exportVideo: jest.fn(),
    createArtifactDownloadGrant: jest.fn(),
  },
}));

jest.mock("../JobListItem", () => ({
  JobListItem: ({
    job,
    isSelected,
    isConfirmingDelete,
    onToggleSelection,
    setConfirmDeleteId,
    onDeleteConfirmed,
    onDownload,
    isDownloading,
  }: {
    job: JobResponse;
    isSelected: boolean;
    isConfirmingDelete: boolean;
    onToggleSelection: (id: string, isSelected: boolean) => void;
    setConfirmDeleteId: (id: string | null) => void;
    onDeleteConfirmed: (id: string) => void;
    onDownload: (job: JobResponse) => void;
    isDownloading: boolean;
  }) => (
    <div data-testid={`job-${job.id}`}>
      <span>{job.result_data?.original_filename}</span>
      <span>{isSelected ? "selected" : "not-selected"}</span>
      <button
        type="button"
        onClick={() => onToggleSelection(job.id, isSelected)}
      >
        toggle-{job.id}
      </button>
      <button type="button" onClick={() => setConfirmDeleteId(job.id)}>
        ask-delete-{job.id}
      </button>
      <button type="button" onClick={() => onDownload(job)}>
        download-{job.id}
      </button>
      <span>{isDownloading ? `downloading-${job.id}` : `idle-${job.id}`}</span>
      {isConfirmingDelete ? (
        <button type="button" onClick={() => onDeleteConfirmed(job.id)}>
          delete-{job.id}
        </button>
      ) : null}
    </div>
  ),
}));

const jobs: JobResponse[] = [
  {
    id: "job-1",
    status: "completed",
    progress: 100,
    message: null,
    created_at: 100,
    updated_at: 100,
    result_data: {
      original_filename: "first.mp4",
      video_path: "/static/artifacts/job-1/processed.mp4",
      public_url: "/static/artifacts/job-1/processed.mp4",
      artifacts_dir: "/artifacts/job-1",
    },
  },
  {
    id: "job-2",
    status: "completed",
    progress: 100,
    message: null,
    created_at: 200,
    updated_at: 200,
    result_data: {
      original_filename: "second.mp4",
      video_path: "/static/artifacts/job-2/processed.mp4",
      public_url: "/static/artifacts/job-2/processed.mp4",
      artifacts_dir: "/artifacts/job-2",
    },
  },
];

function renderList(
  overrides: Partial<React.ComponentProps<typeof RecentJobsList>> = {},
) {
  return render(
    <RecentJobsList
      jobs={jobs}
      isLoading={false}
      onJobSelect={jest.fn()}
      selectedJobId={undefined}
      onRefreshJobs={jest.fn(async () => {})}
      formatDate={() => "2026-04-19"}
      buildStaticUrl={(path) => path ?? null}
      setShowPreview={jest.fn()}
      currentPage={1}
      totalPages={2}
      onNextPage={jest.fn()}
      onPrevPage={jest.fn()}
      totalJobs={4}
      pageSize={2}
      {...overrides}
    />,
  );
}

describe("RecentJobsList", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.exportVideo as jest.Mock).mockImplementation(
      async (jobId: string, resolution: string) => ({
        ...jobs.find((job) => job.id === jobId),
        result_data: {
          ...jobs.find((job) => job.id === jobId)?.result_data,
          variants: {
            [resolution]: `/static/artifacts/${jobId}/processed_${resolution}.mp4`,
          },
        },
      }),
    );
    mockMissingTranslations = false;
    Object.defineProperty(window, "requestAnimationFrame", {
      writable: true,
      value: (callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      },
    });
  });

  it("renders the empty state when there are no jobs", () => {
    renderList({ jobs: [], totalPages: 1, totalJobs: 0 });

    expect(screen.getByText("noHistory")).toBeInTheDocument();
    expect(screen.getByText("noRunsYet")).toBeInTheDocument();
  });

  it("supports batch selection and batch deletion", async () => {
    const onJobSelect = jest.fn();
    const onRefreshJobs = jest.fn(async () => {});
    const setShowPreview = jest.fn();
    (api.deleteJobs as jest.Mock).mockResolvedValue({});

    renderList({
      onJobSelect,
      onRefreshJobs,
      setShowPreview,
      selectedJobId: "job-1",
    });

    fireEvent.click(screen.getByRole("button", { name: "selectMode" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle-job-2" }));

    expect(screen.getByText("2 selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /deleteSelected/i }));
    expect(screen.getByText("deleteSelectedConfirm")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "confirmDelete" }));

    await waitFor(() => {
      expect(api.deleteJobs).toHaveBeenCalledWith(["job-1", "job-2"]);
      expect(onRefreshJobs).toHaveBeenCalled();
      expect(onJobSelect).toHaveBeenCalledWith(null);
      expect(setShowPreview).toHaveBeenCalledWith(false);
    });
  });

  it("cancels selection mode and clears batch state", () => {
    renderList();

    fireEvent.click(screen.getByRole("button", { name: "selectMode" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: /deleteSelected/i }));

    fireEvent.click(screen.getByRole("button", { name: "cancelSelect" }));

    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();
    expect(screen.queryByText("deleteSelectedConfirm")).not.toBeInTheDocument();
  });

  it("deletes a single job and clears the preview when deleting the selected one", async () => {
    const onJobSelect = jest.fn();
    const onRefreshJobs = jest.fn(async () => {});
    const setShowPreview = jest.fn();
    (api.deleteJob as jest.Mock).mockResolvedValue({});

    renderList({
      selectedJobId: "job-1",
      onJobSelect,
      onRefreshJobs,
      setShowPreview,
    });

    fireEvent.click(screen.getByRole("button", { name: "ask-delete-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: "delete-job-1" }));

    await waitFor(() => {
      expect(api.deleteJob).toHaveBeenCalledWith("job-1");
      expect(onJobSelect).toHaveBeenCalledWith(null);
      expect(setShowPreview).toHaveBeenCalledWith(false);
      expect(onRefreshJobs).toHaveBeenCalled();
    });
  });

  it("renders saved captions before granting a History video download", async () => {
    const anchorClick = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    (api.createArtifactDownloadGrant as jest.Mock).mockResolvedValue({
      download_url:
        "/static/artifacts/job-1/processed_1080x1920.mp4?grant=history-grant",
      expires_in: 300,
    });

    renderList();
    fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

    expect(screen.getByText("downloading-job-1")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.exportVideo).toHaveBeenCalledWith("job-1", "1080x1920");
      expect(api.createArtifactDownloadGrant).toHaveBeenCalledWith(
        "job-1",
        "/static/artifacts/job-1/processed_1080x1920.mp4",
        "first_subs.mp4",
      );
      expect(anchorClick).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText("idle-job-1")).toBeInTheDocument();
    });

    const anchor = anchorClick.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.href).toContain(
      "/static/artifacts/job-1/processed_1080x1920.mp4?grant=history-grant",
    );
    expect(anchor.download).toBe("first_subs.mp4");
    anchorClick.mockRestore();
  });

  it("waits for a fresh export even when the History row has an older variant", async () => {
    let finishExport!: (job: JobResponse) => void;
    (api.exportVideo as jest.Mock).mockReturnValue(
      new Promise<JobResponse>((resolve) => {
        finishExport = resolve;
      }),
    );
    const savedJob: JobResponse = {
      ...jobs[0],
      result_data: {
        ...jobs[0].result_data!,
        resolution: "720×1280",
        variants: { "720x1280": "/static/artifacts/job-1/old-captions.mp4" },
      },
    };
    const anchorClick = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    (api.createArtifactDownloadGrant as jest.Mock).mockResolvedValue({
      download_url: "/static/artifacts/job-1/current-captions.mp4?grant=fresh",
      expires_in: 300,
    });

    renderList({ jobs: [savedJob] });
    fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

    expect(api.exportVideo).toHaveBeenCalledWith("job-1", "720x1280");
    expect(screen.getByText("downloading-job-1")).toBeInTheDocument();
    expect(api.createArtifactDownloadGrant).not.toHaveBeenCalled();
    expect(anchorClick).not.toHaveBeenCalled();

    finishExport({
      ...savedJob,
      result_data: {
        ...savedJob.result_data!,
        variants: {
          "720x1280": "/static/artifacts/job-1/current-captions.mp4",
        },
      },
    });
    await waitFor(() => {
      expect(api.createArtifactDownloadGrant).toHaveBeenCalledWith(
        "job-1",
        "/static/artifacts/job-1/current-captions.mp4",
        "first_subs.mp4",
      );
      expect(anchorClick).toHaveBeenCalledTimes(1);
      expect(screen.getByText("idle-job-1")).toBeInTheDocument();
    });
    anchorClick.mockRestore();
  });

  it.each(["render failure", "missing rendered artifact"])(
    "never falls back to the clean preview after %s",
    async (failure) => {
      const errorSpy = jest
        .spyOn(console, "error")
        .mockImplementation(() => {});
      if (failure === "render failure") {
        (api.exportVideo as jest.Mock).mockRejectedValue(
          new Error("render failed"),
        );
      } else {
        (api.exportVideo as jest.Mock).mockResolvedValue(jobs[0]);
      }

      renderList();
      fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "downloadError",
      );
      expect(api.createArtifactDownloadGrant).not.toHaveBeenCalled();
      expect(screen.getByText("idle-job-1")).toBeInTheDocument();
      errorSpy.mockRestore();
    },
  );

  it("shows a retryable error when the history grant cannot be created", async () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    (api.createArtifactDownloadGrant as jest.Mock).mockRejectedValue(
      new Error("grant failed"),
    );

    renderList();
    fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("downloadError");
    expect(errorSpy).toHaveBeenCalledWith(
      "History download failed:",
      expect.any(Error),
    );
    errorSpy.mockRestore();
  });

  it("rejects a grant response that cannot be mapped to a download URL", async () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    (api.createArtifactDownloadGrant as jest.Mock).mockResolvedValue({
      download_url: "/static/artifacts/job-1/processed.mp4?grant=invalid-url",
      expires_in: 300,
    });

    renderList({ buildStaticUrl: () => null });
    fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("downloadError");
    expect(errorSpy).toHaveBeenCalledWith(
      "History download failed:",
      expect.objectContaining({
        message: "Download grant did not include a usable URL",
      }),
    );
    errorSpy.mockRestore();
  });

  it("logs single-delete failures without crashing", async () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    (api.deleteJob as jest.Mock).mockRejectedValue(new Error("delete failed"));

    renderList();

    fireEvent.click(screen.getByRole("button", { name: "ask-delete-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: "delete-job-1" }));

    await waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        "Delete failed:",
        expect.any(Error),
      );
    });
  });

  it("renders pagination controls and forwards page navigation callbacks", () => {
    const onPrevPage = jest.fn();
    const onNextPage = jest.fn();

    renderList({
      currentPage: 2,
      totalPages: 3,
      totalJobs: 5,
      pageSize: 2,
      onPrevPage,
      onNextPage,
    });

    expect(screen.getByText("Showing 3-4 of 5")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /previousPage/i }));
    fireEvent.click(screen.getByRole("button", { name: /nextPage/i }));

    expect(onPrevPage).toHaveBeenCalled();
    expect(onNextPage).toHaveBeenCalled();
  });

  it("toggles individual and select-all choices in both directions", () => {
    renderList();
    fireEvent.click(screen.getByRole("button", { name: "selectMode" }));

    fireEvent.click(screen.getByRole("button", { name: "toggle-job-1" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "toggle-job-1" }));
    expect(screen.getByText("0 selected")).toBeInTheDocument();

    const selectAll = screen.getByRole("checkbox");
    fireEvent.click(selectAll);
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(selectAll);
    expect(screen.getByText("0 selected")).toBeInTheDocument();
  });

  it("keeps batch selection available when deletion fails", async () => {
    const errorSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    (api.deleteJobs as jest.Mock).mockRejectedValue(new Error("batch failed"));
    const onJobSelect = jest.fn();
    const setShowPreview = jest.fn();
    renderList({ selectedJobId: "different-job", onJobSelect, setShowPreview });

    fireEvent.click(screen.getByRole("button", { name: "selectMode" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: /deleteSelected/i }));
    fireEvent.click(screen.getByRole("button", { name: "confirmDelete" }));

    await waitFor(() =>
      expect(errorSpy).toHaveBeenCalledWith(
        "Batch delete failed:",
        expect.any(Error),
      ),
    );
    expect(onJobSelect).not.toHaveBeenCalled();
    expect(setShowPreview).not.toHaveBeenCalled();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(screen.queryByText("deleteSelectedConfirm")).not.toBeInTheDocument();
    errorSpy.mockRestore();
  });

  it("deletes a non-selected job without clearing the current preview", async () => {
    (api.deleteJob as jest.Mock).mockResolvedValue({});
    const onJobSelect = jest.fn();
    const setShowPreview = jest.fn();
    renderList({ selectedJobId: "job-2", onJobSelect, setShowPreview });

    fireEvent.click(screen.getByRole("button", { name: "ask-delete-job-1" }));
    fireEvent.click(screen.getByRole("button", { name: "delete-job-1" }));

    await waitFor(() => expect(api.deleteJob).toHaveBeenCalledWith("job-1"));
    expect(onJobSelect).not.toHaveBeenCalled();
    expect(setShowPreview).not.toHaveBeenCalled();
  });

  it("rejects history downloads that have no artifact path", async () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    const noArtifactJob = {
      ...jobs[0],
      result_data: { original_filename: "missing.mp4" },
    } as JobResponse;
    renderList({ jobs: [noArtifactJob], totalJobs: 1, totalPages: 1 });

    fireEvent.click(screen.getByRole("button", { name: "download-job-1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("downloadError");
    expect(api.exportVideo).not.toHaveBeenCalled();
    expect(api.createArtifactDownloadGrant).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("renders safe English fallbacks, loading state, and bounded page controls", () => {
    mockMissingTranslations = true;
    renderList({
      isLoading: true,
      currentPage: 1,
      totalPages: 2,
      totalJobs: 3,
      pageSize: 2,
      jobs: [
        {
          ...jobs[0],
          updated_at: 0,
          expires_at: 1,
          result_data: {
            ...jobs[0].result_data!,
            public_url: "",
            files_missing: true,
          },
        },
      ],
    });

    expect(screen.getByText("History")).toBeInTheDocument();
    expect(screen.getByText("Items expire in 24 hours")).toBeInTheDocument();
    expect(screen.getByTestId("jobs-loading")).toBeInTheDocument();
    expect(screen.getByText("Showing 1-2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Next/i })).not.toBeDisabled();
  });
});
