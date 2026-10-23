<script lang="ts">
	// OpsPage "sync status per root" (file 08 §4.2) from S1's GET /sync/roots.
	import type { RootStatus } from '$lib/api_endpoint';
	import { ago } from '$lib/components/settings/sources';

	interface Props {
		roots: RootStatus[];
	}

	let { roots }: Props = $props();
	const int = (n: number) => n.toLocaleString('en-US');
</script>

<section class="panel" aria-label="Sync">
	<div class="panel-header flex items-center justify-between gap-2">
		<h2 class="panel-title">Sync per root</h2>
		<a class="text-xs" href="/settings/sources">Sources settings</a>
	</div>
	<table class="data-table">
		<thead><tr><th>Root</th><th>Sign-in</th><th>Kept current by</th><th>Last delta</th><th class="num">Pending</th><th class="num">Failed</th><th class="num">Waiting dispatch</th><th class="num">Errors</th></tr></thead>
		<tbody>
			{#each roots as r (r.root_name)}
				<tr>
					<td>{r.root_name}{#if r.crawl_in_progress}<span class="text-info text-xs">{' · crawling'}</span>{/if}</td>
					<td class={r.auth_status === 'OK' ? '' : 'text-hard font-medium'}>{r.auth_status === 'REAUTH_REQUIRED' ? 'sign-in needed' : r.auth_status}</td>
					<td>{r.kept_current_by}</td>
					<td class="num" title={r.last_delta_at ?? ''}>{ago(r.last_delta_at)}</td>
					<td class="num font-mono">{int(r.counts.pending_download)}</td>
					<td class="num font-mono {r.counts.download_failed ? 'text-hard' : ''}">{int(r.counts.download_failed)}</td>
					<td class="num font-mono">{int(r.counts.waiting_dispatch)}</td>
					<td class="num font-mono {r.recent_errors.length ? 'text-hard' : 'text-muted-foreground'}">{r.recent_errors.length}</td>
				</tr>
			{:else}<tr><td colspan="8" class="text-muted-foreground">No roots configured.</td></tr>{/each}
		</tbody>
	</table>
</section>
