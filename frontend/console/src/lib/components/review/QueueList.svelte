<script lang="ts">
	import type { CaseSummary } from '$lib/api_endpoint';
	import { ageText, caseHref, flagCountsText, isAging } from './format';

	interface Props {
		items: CaseSummary[];
		selectedKey: string | null;
		onOpen: (caseKey: string) => void;
		now?: Date;
	}

	let { items, selectedKey, onOpen, now = new Date() }: Props = $props();
	let cursor = $state(0);

	$effect(() => {
		const index = items.findIndex((item) => item.case_key === selectedKey);
		if (index >= 0) cursor = index;
	});

	function onKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
		if (!items.length) return;
		if (event.key === 'j') cursor = Math.min(cursor + 1, items.length - 1);
		else if (event.key === 'k') cursor = Math.max(cursor - 1, 0);
		else if (event.key === 'Enter') onOpen(items[cursor].case_key);
		else return;
		event.preventDefault();
		document.getElementById(`case-row-${cursor}`)?.scrollIntoView({ block: 'nearest' });
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if items.length === 0}
	<p class="empty">No cases match these filters.</p>
{:else}
	<ol class="queue" aria-label="Review queue">
		{#each items as item, i (item.case_key)}
			<li
				id="case-row-{i}"
				class:cursor={i === cursor}
				class:selected={item.case_key === selectedKey}
				class:aging={isAging(item, now)}
				aria-current={item.case_key === selectedKey ? 'true' : undefined}
			>
				<a
					href={caseHref(item.case_key)}
					onclick={(e) => {
						e.preventDefault();
						cursor = i;
						onOpen(item.case_key);
					}}
				>
					<span class="title">{item.title}{item.page_or_sheet ? ` · ${item.page_or_sheet}` : ''}</span>
					<span class="meta">
						<span class="sev sev-{item.max_severity}">{item.max_severity}</span>
						{flagCountsText(item.flag_counts)}
					</span>
					<span class="meta">
						{#if item.files_unblocked}<span class="impact">unblocks {item.files_unblocked}</span>{/if}
						<span title={item.oldest_created_at}>age {ageText(item.oldest_created_at, now)}</span>
						{#if item.assignee}<span>· {item.assignee}</span>{/if}
						{#if item.has_suggestion}<span class="suggest" title="has a suggested resolution">★</span>{/if}
					</span>
				</a>
			</li>
		{/each}
	</ol>
{/if}

<style>
	.queue {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.25rem;
	}
	li a {
		display: grid;
		gap: 0.15rem;
		padding: 0.45rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 0.35rem;
		background: var(--surface);
		color: inherit;
		text-decoration: none;
		font-size: 0.82rem;
	}
	li.cursor a {
		outline: 2px solid var(--accent);
	}
	li.selected a {
		border-color: var(--accent);
	}
	li.aging a {
		border-left: 4px solid var(--hard);
	}
	.title {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.meta {
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		opacity: 0.85;
	}
	.sev {
		font-weight: 700;
	}
	.sev-HARD {
		color: var(--hard);
	}
	.impact {
		font-weight: 600;
	}
	.suggest {
		color: var(--warn);
	}
	.empty {
		opacity: 0.7;
	}
</style>
