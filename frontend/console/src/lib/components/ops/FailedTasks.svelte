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
	<p class="text-muted-foreground m-0 px-4 py-6 text-center text-[13px]">No failed tasks.</p>
{:else}
	<table class="data-table" aria-label="Failed tasks">
		<thead>
			<tr><th scope="col">When (UTC)</th><th scope="col">Task</th><th scope="col">Queue</th><th scope="col" class="num">Retries</th><th scope="col">Error</th></tr>
		</thead>
		<tbody>
			{#each items as t (t.task_id + t.at)}
				<tr>
					<td class="font-mono text-xs whitespace-nowrap">{when(t.at)}</td>
					<td class="font-mono text-xs" title={t.task}>{shortName(t.task)}</td>
					<td class="font-mono text-xs">{t.queue ?? '—'}</td>
					<td class="num font-mono">{t.retries}</td>
					<td class="min-w-0">
						<details>
							<summary class="text-hard text-[13px] break-words">{t.error}</summary>
							<dl class="kv mt-2">
								<dt>Task id</dt><dd><code>{t.task_id}</code></dd>
								<dt>Task</dt><dd><code class="break-all">{t.task}</code></dd>
								<dt>Args</dt><dd><code class="break-all">{t.args}</code></dd>
								<dt>Kwargs</dt><dd><code class="break-all">{t.kwargs}</code></dd>
							</dl>
						</details>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}
