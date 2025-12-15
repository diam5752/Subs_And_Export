'use client';
import React, { useState } from 'react';
import { JobListItem } from '@/components/JobListItem';
import { JobResponse } from '@/lib/api';

const mockJob: JobResponse = {
    id: 'job-123',
    status: 'completed',
    progress: 100,
    message: null,
    created_at: 1625000000,
    updated_at: 1625000000,
    result_data: {
        video_path: '/path/to/video.mp4',
        artifacts_dir: '/artifacts',
        original_filename: 'test-video.mp4',
        public_url: '#'
    }
};

export default function TestPalettePage() {
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);

    const handleDelete = (id: string) => {
        setIsDeleting(true);
        // Keep it deleting for screenshot purpose
    };

    return (
        <div className="p-10 bg-gray-900 text-white min-h-screen">
            <h1 className="text-2xl mb-4">Test Palette Page</h1>
            <div className="max-w-md space-y-4">
                <div>
                    <h2 className="mb-2">Normal State</h2>
                     <JobListItem
                        job={mockJob}
                        selectionMode={false}
                        isSelected={false}
                        isExpired={false}
                        publicUrl="#"
                        timestamp={1625000000000}
                        formatDate={() => '2021-06-29'}
                        onToggleSelection={() => {}}
                        onJobSelect={() => {}}
                        setShowPreview={() => {}}
                        isConfirmingDelete={false}
                        isDeleting={false}
                        setConfirmDeleteId={() => {}}
                        onDeleteConfirmed={() => {}}
                        t={(k) => k}
                    />
                </div>

                 <div>
                    <h2 className="mb-2">Confirm Delete State</h2>
                     <JobListItem
                        job={{...mockJob, id: 'job-confirm'}}
                        selectionMode={false}
                        isSelected={false}
                        isExpired={false}
                        publicUrl="#"
                        timestamp={1625000000000}
                        formatDate={() => '2021-06-29'}
                        onToggleSelection={() => {}}
                        onJobSelect={() => {}}
                        setShowPreview={() => {}}
                        isConfirmingDelete={true}
                        isDeleting={false}
                        setConfirmDeleteId={() => {}}
                        onDeleteConfirmed={() => {}}
                        t={(k) => k}
                    />
                </div>

                 <div>
                    <h2 className="mb-2">Deleting State (Loading)</h2>
                     <JobListItem
                        job={{...mockJob, id: 'job-deleting'}}
                        selectionMode={false}
                        isSelected={false}
                        isExpired={false}
                        publicUrl="#"
                        timestamp={1625000000000}
                        formatDate={() => '2021-06-29'}
                        onToggleSelection={() => {}}
                        onJobSelect={() => {}}
                        setShowPreview={() => {}}
                        isConfirmingDelete={true}
                        isDeleting={true}
                        setConfirmDeleteId={() => {}}
                        onDeleteConfirmed={() => {}}
                        t={(k) => k === 'deleting' ? 'Deleting...' : k}
                    />
                </div>
            </div>
        </div>
    );
}
