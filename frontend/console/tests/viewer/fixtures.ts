import type { ViewerPayload, ViewerView } from '../../src/lib/api_endpoint';

export const HASH = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08';

export function payload(view: ViewerView, overrides: Partial<ViewerPayload> = {}): ViewerPayload {
	return {
		anchor: `page:12:${HASH}`,
		document: {
			doc_id: '0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90',
			title: 'TP30 hot-fire report',
			doc_kind: 'test_report',
			source_origin: 'internal',
			trust_tier: 2,
			language: 'en',
			test_ids: ['TP30'],
			doc_date: '2026-03-14',
			status: 'ACTIVE_WITH_SOFT_FLAGS',
			open_flags: 1
		},
		resolution: { status: 'exact', message: '' },
		view,
		links: {
			onedrive: [{ path: 'APU Heater/Test Plan 30/report.pdf', web_url: 'https://onedrive.example/report' }],
			download_url: 'https://minio.example/dcl-raw/9f/86/9f86?sig=1',
			review_case_key: '0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90:12'
		},
		translation: { source_language: 'en', available: false, translated_text: null, pending: false },
		...overrides
	};
}

export const PAGE: ViewerView = {
	kind: 'page',
	page_no: 12,
	page_count: 40,
	image_url: 'https://minio.example/dcl-assets/pages/9f86/0012.png?sig=1',
	width: 1240,
	height: 1754,
	regions: [
		{ bbox: [0.1, 0.25, 0.6, 0.3], kind: 'cited', label: 'cited passage', confidence: null },
		{ bbox: [0.7, 0.8, 0.9, 0.85], kind: 'handwriting', label: 'run note', confidence: 0.62 }
	],
	text: 'Chamber pressure peaked at 12.4 bar(a).'
};
