<script lang="ts">
	import type { AuditItem } from '$lib/api_endpoint';
	import { changedKeys, entityHref } from './audit';

	interface Props {
		items: AuditItem[];
	}

	let { items }: Props = $props();
	const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
</script>

{#if items.length === 0}
	<p class="muted">No audit events match these filters.</p>
{:else}
	<ol class="timeline" aria-label="Audit events">
		{#each items as item (item.event_id)}
			{@const href = entityHref(item)}
			{@const changed = changedKeys(item.before ?? null, item.after ?? null)}
			<li>
				<div class="line">
					<time datetime={item.at}>{when(item.at)}</time>
					<strong>{item.actor}</strong>
					<span class="action">{item.action}</span>
					<span class="entity">{item.entity_type}</span>
					{#if href}<a {href}>{item.entity_id}</a>{:else}<code>{item.entity_id}</code>{/if}
				</div>
				{#if changed.length}
					<details>
						<summary>Changed: {changed.join(', ')}</summary>
						<div class="diff">
							<div>
								<h4>Before</h4>
								<pre>{JSON.stringify(item.before, null, 2)}</pre>
							</div>
							<div>
								<h4>After</h4>
								<pre>{JSON.stringify(item.after, null, 2)}</pre>
							</div>
						</div>
					</details>
				{/if}
			</li>
		{/each}
	</ol>
{/if}

<style>
	.timeline {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.4rem;
	}
	li {
		border-left: 3px solid var(--border);
		padding: 0.35rem 0.6rem;
		background: var(--surface);
		font-size: 0.84rem;
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		align-items: baseline;
	}
	time {
		opacity: 0.75;
		font-variant-numeric: tabular-nums;
	}
	.action {
		font-weight: 600;
	}
	.entity {
		opacity: 0.7;
	}
	a,
	code {
		overflow-wrap: anywhere;
	}
	.diff {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.6rem;
	}
	@media (max-width: 700px) {
		.diff {
			grid-template-columns: 1fr;
		}
	}
	h4 {
		margin: 0.3rem 0 0.1rem;
		font-size: 0.75rem;
		opacity: 0.7;
	}
	pre {
		margin: 0;
		font-size: 0.76rem;
		white-space: pre-wrap;
	}
	.muted {
		opacity: 0.7;
	}
</style>
