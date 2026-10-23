<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import type { AuditItem } from '$lib/api_endpoint';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import { changedKeys, decisionsHref, entityHref } from './audit';

	interface Props {
		items: AuditItem[];
	}

	let { items }: Props = $props();
	const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
	const COLS = 'grid grid-cols-[10.5rem_minmax(8rem,14rem)_8rem_7rem_minmax(0,1fr)] items-baseline gap-x-4';
</script>

{#if items.length === 0}
	<EmptyState title="No audit events match these filters." description="Widen the date range or clear the filters." />
{:else}
	<!-- overflow-clip, not overflow-hidden: hidden makes the panel a scroll box and pins the sticky header 3rem down inside it -->
	<div class="panel overflow-clip">
		<div
			class="{COLS} bg-background text-muted-foreground sticky top-[var(--sticky-top,0px)] z-10 h-8 border-b px-4 text-xs leading-8 font-medium"
			aria-hidden="true"
		>
			<span>Time</span><span>Actor</span><span>Action</span><span>Entity</span><span>Id</span>
		</div>
		<ol class="m-0 list-none divide-y p-0" aria-label="Audit events">
			{#each items as item (item.event_id)}
				{@const href = entityHref(item)}
				{@const changed = changedKeys(item.before ?? null, item.after ?? null)}
				<li class="hover:bg-muted/40 px-4 py-2 transition-colors">
					<div class={COLS}>
						<time class="num text-muted-foreground font-mono text-xs" datetime={item.at}>{when(item.at)}</time>
						<strong class="truncate font-medium" title={item.actor}>{item.actor}</strong>
						<span class="font-mono text-xs font-medium">{item.action}</span>
						<span class="text-muted-foreground text-xs">{item.entity_type}</span>
						<span class="min-w-0 break-all">
							{#if href}<a {href} class="font-mono text-xs">{item.entity_id}</a>{:else}<code>{item.entity_id}</code>{/if}
							{#if item.entity_type === 'case'}<a href={decisionsHref(item.entity_id)} class="ml-2 text-xs whitespace-nowrap">Decisions and edit</a>{/if}
						</span>
					</div>
					{#if changed.length}
						<details class="group mt-1.5">
							<summary class="text-muted-foreground hover:text-foreground flex w-fit list-none items-center gap-1 rounded-sm text-xs [&::-webkit-details-marker]:hidden">
								<ChevronRightIcon class="size-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />Changed: {changed.join(', ')}
							</summary>
							<div class="mt-2 grid gap-3 lg:grid-cols-2">
								<div>
									<h4 class="eyebrow mb-1">Before</h4>
									<pre class="code-block m-0">{JSON.stringify(item.before, null, 2)}</pre>
								</div>
								<div>
									<h4 class="eyebrow mb-1">After</h4>
									<pre class="code-block m-0">{JSON.stringify(item.after, null, 2)}</pre>
								</div>
							</div>
						</details>
					{/if}
				</li>
			{/each}
		</ol>
	</div>
{/if}
