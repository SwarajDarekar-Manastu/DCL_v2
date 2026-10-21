<script lang="ts">
	import type { CaseDetail } from '$lib/api_endpoint';
	import { ageText, isAging } from './format';

	interface Props {
		detail: CaseDetail;
		me: string;
		busy: boolean;
		onAssign: (assignee: string | null) => void;
		onUndo: () => void;
	}

	let { detail, me, busy, onAssign, onUndo }: Props = $props();
	let summary = $derived(detail.summary);
	let hardOpen = $derived(detail.flags.filter((f) => f.severity === 'HARD' && ['OPEN', 'IN_PROGRESS', 'REOPENED'].includes(f.status)).length);
	let undoable = $derived(detail.flags.some((f) => f.status === 'RESOLVED' || f.status === 'REJECTED_FILE'));
	let pageNo = $derived(/^\d+$/.test(summary.page_or_sheet) ? Number(summary.page_or_sheet) : null);
	let viewerHref = $derived(
		summary.doc_id ? `/docs/${summary.doc_id}/viewer${pageNo ? `?anchor=${encodeURIComponent(`page:${pageNo}:`)}` : ''}` : null
	);
</script>

<header class="case-header">
	<div class="title">
		<h2>
			{summary.root_name ? `${summary.root_name} / ` : ''}{summary.title}{summary.page_or_sheet ? ` · ${summary.page_or_sheet}` : ''}
		</h2>
		<p class="meta">
			{#if hardOpen}<span class="hard">{hardOpen} HARD flag{hardOpen === 1 ? '' : 's'}</span> ·{/if}
			{summary.status}{summary.route ? ` · route ${summary.route}` : ''}{detail.document_status ? ` · document ${detail.document_status}` : ''}
			· <span class:aging={isAging(summary)}>age {ageText(summary.oldest_created_at)}</span>
			· {summary.assignee ? `assigned to ${summary.assignee}` : 'unassigned'}
		</p>
		{#if summary.path}<p class="path">{summary.path}</p>{/if}
	</div>
	<div class="actions">
		{#each detail.locations as location (location.path)}
			{#if location.web_url}<a href={location.web_url} target="_blank" rel="noopener noreferrer">Open folder in OneDrive</a>{/if}
		{/each}
		{#if viewerHref}<a href={viewerHref}>Open in viewer</a>{/if}
		{#if summary.assignee === me}
			<button type="button" disabled={busy} onclick={() => onAssign(null)}>Unassign</button>
		{:else}
			<button type="button" disabled={busy} onclick={() => onAssign(me)}>Assign to me</button>
		{/if}
		<button type="button" disabled={busy || !undoable} onclick={onUndo}>Undo last resolution</button>
	</div>
</header>

<style>
	.case-header {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		justify-content: space-between;
		align-items: start;
	}
	h2 {
		margin: 0;
		font-size: 1.05rem;
		overflow-wrap: anywhere;
	}
	.meta,
	.path {
		margin: 0.2rem 0 0;
		font-size: 0.8rem;
		opacity: 0.85;
	}
	.path {
		overflow-wrap: anywhere;
	}
	.hard,
	.aging {
		color: var(--hard);
		font-weight: 600;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		font-size: 0.82rem;
	}
	button {
		font: inherit;
		padding: 0.25rem 0.65rem;
		cursor: pointer;
	}
</style>
