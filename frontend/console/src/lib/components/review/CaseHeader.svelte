<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import FileTextIcon from '@lucide/svelte/icons/file-text';
	import HistoryIcon from '@lucide/svelte/icons/history';
	import Undo2Icon from '@lucide/svelte/icons/undo-2';
	import type { CaseDetail } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import { auditUrl } from './audit';
	import { ageText, isAging } from './format';
	import { groupLocations, shortFolder } from './locations';

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
	let places = $derived(groupLocations(detail.locations));
	let historyHref = $derived(auditUrl({ entity_id: [summary.case_key, ...detail.flags.map((f) => f.flag_id)] }));
	let viewerHref = $derived(
		summary.doc_id ? `/docs/${summary.doc_id}/viewer${pageNo ? `?anchor=${encodeURIComponent(`page:${pageNo}:`)}` : ''}` : null
	);
</script>

<header class="grid gap-3">
	<div class="min-w-0">
		<h2 class="m-0 text-base leading-6 break-words">
			{#if summary.root_name}<span class="text-muted-foreground font-normal">{summary.root_name} / </span>{/if}{summary.title}{#if summary.page_or_sheet}<span
					class="text-muted-foreground font-normal">{` · ${summary.page_or_sheet}`}</span
				>{/if}
		</h2>
		<p class="text-muted-foreground m-0 mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
			{#if hardOpen}<ToneBadge tone="hard">{hardOpen} HARD flag{hardOpen === 1 ? '' : 's'}</ToneBadge>{/if}
			<ToneBadge tone="outline">{summary.status}</ToneBadge>
			{#if summary.route}<span>route <span class="text-foreground font-mono">{summary.route}</span></span>{/if}
			{#if detail.document_status}<span>· document <span class="text-foreground">{detail.document_status}</span></span>{/if}
			<span>·</span>
			<span class={isAging(summary) ? 'text-hard font-semibold' : ''} title={summary.oldest_created_at}>age {ageText(summary.oldest_created_at)}</span>
			<span>· {summary.assignee ? `assigned to ${summary.assignee}` : 'unassigned'}</span>
		</p>
		{#if summary.path}<p class="text-muted-foreground m-0 mt-1 font-mono text-xs break-all">{summary.path}</p>{/if}
	</div>
	<div class="flex flex-wrap items-center gap-1.5">
		{#if summary.assignee === me}
			<Button variant="outline" size="sm" disabled={busy} onclick={() => onAssign(null)}>Unassign</Button>
		{:else}
			<Button size="sm" disabled={busy} onclick={() => onAssign(me)}>Assign to me</Button>
		{/if}
		<Button variant="outline" size="sm" disabled={busy || !undoable} onclick={onUndo}><Undo2Icon />Undo last resolution</Button>
		<span class="bg-border mx-1 h-4 w-px" aria-hidden="true"></span>
		{#if viewerHref}<Button variant="ghost" size="sm" href={viewerHref}><FileTextIcon />Open in viewer</Button>{/if}
		<Button variant="ghost" size="sm" href={historyHref}><HistoryIcon />History</Button>
		{#if places.primary}
			<Button variant="ghost" size="sm" href={places.primary.url} target="_blank" rel="noopener noreferrer" title={places.primary.folder}
				><ExternalLinkIcon />Open in OneDrive</Button
			>
		{/if}
		{#if places.others.length}
			<details class="relative">
				<summary class="text-muted-foreground hover:text-foreground cursor-pointer text-xs select-none">{places.others.length} other cop{places.others.length === 1 ? 'y' : 'ies'}</summary>
				<ul class="bg-popover absolute z-20 mt-1 grid max-h-64 w-80 max-w-[90vw] list-none gap-0.5 overflow-auto rounded-md border p-2 text-xs shadow-md">
					{#each places.others as link (link.url)}
						<li>
							<a class="hover:underline" href={link.url} target="_blank" rel="noopener noreferrer" title={link.folder}
								>{shortFolder(link.folder)} <span class="text-muted-foreground">· {link.file}</span></a
							>
						</li>
					{/each}
				</ul>
			</details>
		{/if}
	</div>
</header>
