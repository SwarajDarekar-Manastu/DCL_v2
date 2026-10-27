import { describe, expect, it } from 'vitest';
import { fileStatusNote, reasonOf } from '../../src/lib/components/review/file_status';
import { unitFlag } from './fixtures';

const decided = unitFlag({ status: 'RESOLVED' });
const base = { flags: [decided], document_error: null, document_retries: false, document_blocking: 0 };

describe('fileStatusNote', () => {
	it('says a decided HALTED file resumes on its own, or why its resume failed', () => {
		expect(fileStatusNote({ ...base, document_status: 'HALTED', document_retries: true })).toEqual({
			tone: 'info',
			text: 'Decided. The file resumes on its own within 30 minutes.'
		});
		const failed = { ...base, document_status: 'HALTED', document_retries: true, document_error: 'S3Error: S3 operation failed; code: XMinioStorageFull' };
		expect(fileStatusNote(failed)?.text).toBe('Decided, but resuming the file failed: the storage is full. It is tried again on its own.');
	});

	it('names the blocking questions left in the file’s other cases', () => {
		expect(fileStatusNote({ ...base, document_status: 'HALTED', document_blocking: 2 })?.text).toBe(
			'This file stays out of search until its other 2 blocking questions are answered.'
		);
	});

	it('stays quiet while this case still has an open HARD question, and on a searchable file', () => {
		expect(fileStatusNote({ ...base, flags: [unitFlag()], document_status: 'HALTED' })).toBeNull();
		expect(fileStatusNote({ ...base, document_status: 'ACTIVE' })).toBeNull();
	});

	it('tells a FAILED file that retries itself from one that needs a person', () => {
		expect(fileStatusNote({ ...base, document_status: 'FAILED', document_retries: true, document_error: 'GatewayError: gateway unreachable: ConnectError' })?.text).toBe(
			'Processing this file failed: the model gateway could not be reached. It is tried again on its own.'
		);
		expect(fileStatusNote({ ...base, document_status: 'FAILED', document_error: 'ValueError: bad page tree' })?.text).toBe(
			'Processing this file failed: bad page tree. Re-run it from Ops once the cause is fixed.'
		);
	});
});

describe('reasonOf', () => {
	it('shortens a long error', () => {
		expect(reasonOf(`ValueError: ${'x'.repeat(300)}`)).toHaveLength(158);
	});
});
