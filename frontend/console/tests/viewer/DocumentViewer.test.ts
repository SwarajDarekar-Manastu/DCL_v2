import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import DocumentViewer from '../../src/lib/components/viewer/DocumentViewer.svelte';
import { PAGE, payload } from './fixtures';

const pageHref = (n: number) => `/docs/d/viewer?anchor=page%3A${n}%3A`;

function show(p = payload(PAGE), translating = false, onToggleTranslate = () => {}) {
	return render(DocumentViewer, { payload: p, translating, onToggleTranslate, pageHref });
}

describe('DocumentViewer', () => {
	it('shows the page render with its regions and no fallback notice on an exact match', () => {
		show();
		expect(screen.getByRole('img').getAttribute('src')).toBe(PAGE.kind === 'page' ? PAGE.image_url : '');
		expect(screen.getAllByTestId('region')).toHaveLength(2);
		expect(screen.queryByRole('status')).toBeNull();
		expect(screen.getByText('Page 12 of 40')).toBeTruthy();
		expect(screen.getByRole('link', { name: '← Page 11' }).getAttribute('href')).toBe(pageHref(11));
	});

	it('says explicitly when it fell back to the page because the content changed', () => {
		show(payload(PAGE, { resolution: { status: 'page_fallback', message: 'hash 9f86… not found on page 12' } }));
		const notice = screen.getByRole('status');
		expect(notice.dataset.status).toBe('page_fallback');
		expect(notice.textContent).toContain('changed since it was cited');
		expect(notice.textContent).toContain('hash 9f86… not found on page 12');
	});

	it('says when the cited location is gone', () => {
		show(payload({ kind: 'text', text: 'start of document', breadcrumb: '' }, { resolution: { status: 'document_only', message: '' } }));
		expect(screen.getByRole('status').textContent).toContain('no longer exists');
	});

	it('switches the page between image and extracted text', async () => {
		show();
		await fireEvent.click(screen.getByRole('button', { name: 'Show text' }));
		expect(screen.getByText('Chamber pressure peaked at 12.4 bar(a).')).toBeTruthy();
		expect(screen.queryByRole('img')).toBeNull();
	});

	it('renders table cells as text and highlights the cited range', () => {
		const { container } = show(
			payload({ kind: 'table', sheet_name: 'Run 1', header_rows: 1, rows: [['t_s', 'p_bar'], ['0.1', '<b>12.4</b>']], highlight: [1, 1, 1, 1] })
		);
		expect(screen.getByText('<b>12.4</b>').classList.contains('lit')).toBe(true);
		expect(container.querySelector('b')).toBeNull();
		expect(screen.getByText('Sheet: Run 1')).toBeTruthy();
	});

	it('numbers code lines from first_line and highlights the cited lines', () => {
		const { container } = show(payload({ kind: 'code', language: 'python', first_line: 41, lines: ['a = 1', 'b = 2', 'c = 3'], highlight: [42, 43] }));
		const lit = [...container.querySelectorAll('.line.lit')].map((el) => (el as HTMLElement).dataset.line);
		expect(lit).toEqual(['42', '43']);
	});

	it('seeks the video to the anchor time', () => {
		const { container } = show(payload({ kind: 'video', video_url: 'https://minio.example/v.mp4?sig=1', t_ms: 83500, poster_url: null }));
		expect(container.querySelector('video')?.getAttribute('src')).toBe('https://minio.example/v.mp4?sig=1#t=83.500');
	});

	it('offers translation for non-English documents and shows the marker', async () => {
		const toggle = vi.fn();
		const german = payload(PAGE, {
			translation: { source_language: 'de', available: true, translated_text: 'Preheat power 4 W.', pending: false }
		});
		show(german, false, toggle);
		await fireEvent.click(screen.getByRole('button', { name: 'Translate' }));
		expect(toggle).toHaveBeenCalledOnce();

		show(german, true);
		expect(screen.getByText(/Translated from de/)).toBeTruthy();
		expect(screen.getByText('Preheat power 4 W.')).toBeTruthy();
	});

	it('links OneDrive, the original and the open review case without node ids', () => {
		show();
		expect(screen.getByRole('link', { name: 'Open in OneDrive' }).getAttribute('href')).toBe('https://onedrive.example/report');
		expect(screen.getByRole('link', { name: 'Open review case' }).getAttribute('href')).toBe(
			'/review?case=0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90%3A12'
		);
		expect(screen.queryByRole('button', { name: 'Translate' })).toBeNull();
	});
});
