// The pipeline steps the Ops page counts files in (backend/api/file_steps.py), in words.

import type { Step } from '$lib/api_endpoint';

export const STEP_GROUPS: { title: string; steps: Step[] }[] = [
	{ title: 'OneDrive', steps: ['to_download', 'held', 'skipped', 'outside_scope'] },
	{ title: 'Processing', steps: ['waiting', 'in_line', 'processing', 'review', 'failed', 'in_search', 'taken_out'] }
];

export const STEP_LABEL: Record<Step, string> = {
	to_download: 'To download',
	held: 'Held back',
	skipped: 'Skipped',
	outside_scope: 'Outside the processing scope',
	waiting: 'Waiting to start',
	in_line: 'In line',
	processing: 'Processing now',
	review: 'Waiting for review',
	failed: 'Failed',
	in_search: 'In search',
	taken_out: 'Taken out'
};

export const STEP_HINT: Record<Step, string> = {
	to_download: 'Found in OneDrive and not downloaded yet.',
	held: 'Too large, outside the download scope, in a quarantine folder, restricted, or the download failed.',
	skipped: 'Left out on purpose: junk, empty files, shortcuts and unsupported packages.',
	outside_scope: 'Downloaded, in folders the processing scope does not include.',
	waiting: 'Inside the processing scope and not started: not yet made into a document, or its route is not switched on.',
	in_line: 'Sent for processing and waiting for a free worker. Workers take one file at a time.',
	processing: 'A worker is processing it right now.',
	review: 'Stopped on a review question; it goes on once the question is answered.',
	failed: 'Processing failed. The reason is shown per file.',
	in_search: 'Processed and searchable.',
	taken_out: 'Out of search: replaced by a newer version, deleted in OneDrive, or taken out in review.'
};
