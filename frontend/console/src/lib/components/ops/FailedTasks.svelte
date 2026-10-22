<script lang="ts">
	import type { FailedTask } from '$lib/api_endpoint';

	interface Props {
		items: FailedTask[];
	}

	let { items }: Props = $props();

	const shortName = (task: string) => task.split('.').at(-1) ?? task;
	const when = (at: string) => at.slice(0, 19).replace('T', ' ');
</script>

{#if items.length === 0}
	<p class="muted">No failed tasks.</p>
{:else}
	<table class="grid" aria-label="Failed tasks">
		<thead><tr><th>When (UTC)</th><th>Task</th><th>Queue</th><th>Retries</th><th>Error</th></tr></thead>
		<tbody>
			{#each items as t (t.task_id + t.at)}
				<tr>
					<td>{when(t.at)}</td>
					<td title={t.task}>{shortName(t.task)}</td>
					<td>{t.queue ?? '—'}</td>
					<td>{t.retries}</td>
					<td>
						<details>
							<summary>{t.error}</summary>
							<dl>
								<dt>Task id</dt><dd><code>{t.task_id}</code></dd>
								<dt>Task</dt><dd><code>{t.task}</code></dd>
								<dt>Args</dt><dd><code>{t.args}</code></dd>
								<dt>Kwargs</dt><dd><code>{t.kwargs}</code></dd>
							</dl>
						</details>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.grid {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.84rem;
	}
	.grid th,
	.grid td {
		border-bottom: 1px solid var(--border);
		padding: 0.3rem 0.5rem;
		text-align: left;
		vertical-align: top;
	}
	summary {
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.2rem 0.6rem;
		margin: 0.4rem 0 0;
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.muted {
		opacity: 0.7;
	}
</style>
