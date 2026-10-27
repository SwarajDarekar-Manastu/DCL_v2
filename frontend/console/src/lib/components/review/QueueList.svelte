<script lang="ts">
	import SparklesIcon from '@lucide/svelte/icons/sparkles';
	import type { CaseSummary } from '$lib/api_endpoint';
	import SeverityBadge from '$lib/components/shell/SeverityBadge.svelte';
	import { cn } from '$lib/utils';
	import { ageText, caseHref, isAging, placeText, questionText } from './format';

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
		// Keys typed into a field, or pressed on a button (Enter on "Apply"), belong to that control.
		const target = event.target;
		if (target instanceof Element && target.closest('input, select, textarea, button, [contenteditable="true"]')) return;
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
	<p class="text-muted-foreground m-0 px-4 py-8 text-center text-[13px]">No cases match these filters.</p>
{:else}
	<ol class="m-0 list-none p-0" aria-label="Review queue">
		{#each items as item, i (item.case_key)}
			{@const aging = isAging(item, now)}
			{@const selected = item.case_key === selectedKey}
			<li
				id="case-row-{i}"
				class={cn('relative border-b', aging && 'aging', i === cursor && 'cursor')}
				aria-current={selected ? 'true' : undefined}
			>
				<a
					href={caseHref(item.case_key)}
					class={cn(
						'text-foreground hover:bg-muted/60 grid gap-1 py-2.5 pr-3 pl-4 no-underline transition-colors hover:no-underline focus-visible:-outline-offset-2',
						selected && 'bg-muted hover:bg-muted',
						i === cursor && !selected && 'bg-muted/40'
					)}
					onclick={(e) => {
						e.preventDefault();
						cursor = i;
						onOpen(item.case_key);
					}}
				>
					<span class="flex min-w-0 items-start gap-2">
						<SeverityBadge severity={item.max_severity} class="mt-px" />
						<span class="min-w-0 flex-1 text-[13px] leading-5 font-medium break-words"
							>{item.title}{#if item.page_or_sheet}<span class="text-muted-foreground font-normal">{` · ${placeText(item.page_or_sheet)}`}</span>{/if}</span
						>
						{#if item.has_suggestion}<span class="text-info mt-0.5" title={item.has_rule_proposal ? 'a rule proposes its units' : 'has a suggested resolution'}
								><SparklesIcon class="size-3.5" aria-hidden="true" /><span class="sr-only">{item.has_rule_proposal ? 'rule proposal' : 'has suggestion'}</span></span
							>{/if}
					</span>
					<span class="text-muted-foreground text-xs leading-4">{questionText(item.flag_counts)}</span>
					<span class="text-muted-foreground num flex flex-wrap gap-x-2 text-xs">
						{#if item.files_unblocked}<span class="text-foreground font-medium">unblocks {item.files_unblocked}</span>{/if}
						<span class={aging ? 'text-hard font-medium' : ''} title={item.oldest_created_at}>age {ageText(item.oldest_created_at, now)}</span>
						{#if item.assignee}<span class="truncate">· {item.assignee}</span>{/if}
					</span>
				</a>
				{#if selected}<span class="bg-foreground absolute inset-y-0 left-0 w-0.5" aria-hidden="true"></span>
				{:else if aging}<span class="bg-hard absolute inset-y-0 left-0 w-0.5" aria-hidden="true"></span>{/if}
			</li>
		{/each}
	</ol>
{/if}
