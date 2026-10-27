// What became of the case's file after its decisions (plan B1, 2026-10-27): a decided file that has not moved
// on is said in words, never left as a bare status. The reconciler (backend/dispatcher/reconcile.py) sends it
// again on its own.

import type { CaseDetail } from '$lib/api_endpoint';

export interface FileStatusNote {
	tone: 'info' | 'warning' | 'error';
	text: string;
}

const OPEN = ['OPEN', 'IN_PROGRESS', 'REOPENED'];

/** A short reason for a recorded processing error. */
export function reasonOf(error: string): string {
	if (error.includes('XMinioStorageFull')) return 'the storage is full';
	if (/gateway unreachable|GatewayUnavailable/i.test(error)) return 'the model gateway could not be reached';
	if (/ModelServerUnavailable/.test(error)) return 'the models service could not be reached';
	const plain = error.replace(/^[A-Za-z]+Error: /, '');
	return plain.length > 160 ? `${plain.slice(0, 157)}…` : plain;
}

export function fileStatusNote(
	detail: Pick<CaseDetail, 'flags' | 'document_status' | 'document_error' | 'document_retries' | 'document_blocking'>
): FileStatusNote | null {
	const status = detail.document_status;
	const error = detail.document_error ? reasonOf(detail.document_error) : null;
	if (status === 'FAILED') {
		const next = detail.document_retries ? 'It is tried again on its own.' : 'Re-run it from Ops once the cause is fixed.';
		return { tone: 'error', text: `Processing this file failed${error ? `: ${error}` : ''}. ${next}` };
	}
	if (status === 'PROCESSING') {
		return { tone: 'info', text: 'This file is being rebuilt with the decisions; search shows them when it finishes.' };
	}
	const openHere = detail.flags.some((f) => f.severity === 'HARD' && OPEN.includes(f.status));
	if (status !== 'HALTED' || openHere) return null;
	const blocking = detail.document_blocking ?? 0;
	if (blocking > 0) {
		return {
			tone: 'warning',
			text: `This file stays out of search until its other ${blocking} blocking question${blocking === 1 ? ' is' : 's are'} answered.`
		};
	}
	if (error) return { tone: 'warning', text: `Decided, but resuming the file failed: ${error}. It is tried again on its own.` };
	return { tone: 'info', text: 'Decided. The file resumes on its own within 30 minutes.' };
}
