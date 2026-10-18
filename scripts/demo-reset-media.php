<?php
/**
 * demo-reset-media.php - delete orphan media from the demo store.
 *
 * Runs INSIDE the wordpress pod (`kubectl exec -i <wp-pod> -c wordpress -- php`)
 * because deleting attachments via wp_delete_attachment() needs the WordPress DB
 * and the upload filesystem, which only that pod has. The Woo consumer key cannot
 * authenticate wp/v2/media (it is a wc/*-only credential), and the F3 image route
 * deliberately has no delete endpoint (docs/DECISIONS.md ADR-035), so this is the
 * safe, capability-scoped path.
 *
 * Rule (mirrors scripts/demo-seeds.json "media_rule"): an attachment is KEPT iff
 * it is the featured thumbnail of one of the 12 seeded products (matched by SKU
 * from store/products.json, the single source of truth); every other attachment
 * is deleted. Unattached test uploads and images left over from deleted test
 * products are therefore removed, and the seed product images are never touched.
 *
 * Set MEDIA_DRY_RUN=1 in the environment to list what would be deleted without
 * deleting (demo-reset.sh passes it for the plan phase).
 *
 * Output: one line per deleted media id, then "media summary: kept=N deleted=N".
 */

$dry_run = getenv( 'MEDIA_DRY_RUN' ) === '1';

if ( ! defined( 'ABSPATH' ) ) {
    require dirname( __DIR__, 2 ) . '/wp-load.php'; // <html>/wp-load.php relative to wp-content
}

if ( ! function_exists( 'wc_get_product_id_by_sku' ) ) {
    fwrite( STDERR, "WooCommerce not loaded\n" );
    exit( 1 );
}

$json_path = WP_CONTENT_DIR . '/store/products.json';
$raw       = file_exists( $json_path ) ? file_get_contents( $json_path ) : '';
$data      = $raw ? json_decode( $raw, true ) : null;
$skus      = array();
if ( is_array( $data ) && ! empty( $data['products'] ) ) {
    foreach ( $data['products'] as $p ) {
        $sku = (string) ( $p['sku'] ?? '' );
        if ( '' !== $sku ) {
            $skus[] = $sku;
        }
    }
}

$keep_ids = array();
foreach ( $skus as $sku ) {
    $pid = wc_get_product_id_by_sku( $sku );
    if ( $pid ) {
        $tid = get_post_thumbnail_id( $pid );
        if ( $tid ) {
            $keep_ids[ (int) $tid ] = true;
        }
    }
}

$attachments = get_posts(
    array(
        'post_type'      => 'attachment',
        'post_status'    => 'inherit',
        'posts_per_page' => -1,
        'fields'         => 'ids',
        'no_found_rows'  => true,
    )
);

$kept    = 0;
$deleted = 0;
foreach ( $attachments as $id ) {
    if ( isset( $keep_ids[ (int) $id ] ) ) {
        $kept++;
        continue;
    }
    if ( $dry_run ) {
        echo "  WOULD delete media #$id\n";
        $deleted++;
        continue;
    }
    if ( wp_delete_attachment( (int) $id, true ) ) {
        $deleted++;
        echo "  deleted media #$id\n";
    } else {
        fwrite( STDERR, "  FAILED to delete media #$id\n" );
    }
}

echo "media summary: kept=$kept deleted=$deleted" . ( $dry_run ? ' (dry run)' : '' ) . "\n";
