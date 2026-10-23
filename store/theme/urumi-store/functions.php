<?php
/**
 * Loam & Ember store theme bootstrap (store v3 theme, ADR-076..078).
 *
 * Standalone block theme. This file wires:
 *  - the theme stylesheet (assets/styles.css) on top of theme.json
 *  - self-hosted font preloads (Newsreader + Hanken Grotesk variable, no externals)
 *  - removal of every third-party hook: emoji scripts, gravatars, oEmbed
 *  - dynamic blocks: urumi-store/hero, urumi-store/categories, urumi-store/category-banner,
 *    urumi-store/featured-grid, urumi-store/new-badge, urumi-store/editorial,
 *    urumi-store/product-meta
 *  - a registered 600px image size so sideloaded 1200px photos get an exact
 *    600px derivative and real srcset values
 *  - tile flags (sale / new / sold out) injected into WooCommerce block grids
 *  - a stock-state line injected above the add-to-cart form on the product page
 *
 * The catalog (wp-content/store/products.json) is the single source of truth.
 * The hero, editorial and category-tile photos come from catalog entries
 * ("hero", "editorial", per-product "image"); until photos are curated every
 * frame falls back to a plain beige block, never to a broken image. "New" is
 * the _urumi_is_new product meta (set by the wp-setup seed); "featured" is
 * Woo's featured flag.
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'URUMI_STORE_VERSION', '3.1.0' );
define( 'URUMI_STORE_BRAND', 'Loam & Ember' );

/**
 * Absolute path to the deployed store data dir (wp-content/store is copied by
 * the store-assets initContainer and is the single source of truth).
 */
function urumi_store_data_dir() {
	return WP_CONTENT_DIR . '/store';
}

/**
 * Read the catalog JSON (products.json). Returns the decoded array or empty.
 */
function urumi_store_catalog() {
	static $catalog = null;
	if ( null !== $catalog ) {
		return $catalog;
	}
	$path = urumi_store_data_dir() . '/products.json';
	if ( ! file_exists( $path ) ) {
		$catalog = array();
		return $catalog;
	}
	$json = wp_json_file_decode( $path, array( 'associative' => true ) );
	$catalog = ( is_array( $json ) ) ? $json : array();
	return $catalog;
}

/**
 * Read the catalog products. Returns the decoded product array or empty.
 */
function urumi_store_products() {
	static $products = null;
	if ( null !== $products ) {
		return $products;
	}
	$catalog = urumi_store_catalog();
	$products = ( isset( $catalog['products'] ) && is_array( $catalog['products'] ) ) ? $catalog['products'] : array();
	return $products;
}

/** Products keyed by SKU. */
function urumi_store_products_by_sku() {
	$out = array();
	foreach ( urumi_store_products() as $p ) {
		if ( ! empty( $p['sku'] ) ) {
			$out[ $p['sku'] ] = $p;
		}
	}
	return $out;
}

/**
 * Format a numeric price string as USD with the store's exact decimals.
 * e.g. "12" -> "$12.00", "149.99" -> "$149.99".
 */
function urumi_store_format_price( $price ) {
	$n = is_numeric( $price ) ? (float) $price : 0.0;
	return '$' . number_format( $n, 2, '.', '' );
}

/** URL to a store asset (image) inside wp-content/store. */
function urumi_store_asset_url( $path ) {
	return content_url( 'store/' . ltrim( $path, '/' ) );
}

/** Image URL for a catalog product entry (its main photo file). */
function urumi_store_image_url( $p ) {
	$name = isset( $p['image'] ) ? $p['image'] : ( $p['sku'] . '.webp' );
	return urumi_store_asset_url( 'images/' . $name );
}

/** URL to a store image file, if it exists on disk. */
function urumi_store_image_if_exists( $file ) {
	if ( ! $file ) {
		return '';
	}
	if ( file_exists( urumi_store_data_dir() . '/images/' . $file ) ) {
		return urumi_store_asset_url( 'images/' . $file );
	}
	return '';
}

/**
 * Remove every third-party hook so the storefront makes zero external requests.
 */
function urumi_store_disable_third_party() {
	// Emoji: the inline detection script and the front-end emoji styles.
	remove_action( 'wp_head', 'print_emoji_detection_script', 7 );
	remove_action( 'wp_print_styles', 'print_emoji_styles' );
	remove_action( 'admin_print_scripts', 'print_emoji_detection_script' );
	remove_action( 'admin_print_styles', 'print_emoji_styles' );

	// Gravatars: no remote avatar fetch, ever.
	add_filter( 'option_show_avatars', '__return_false' );

	// oEmbed: no discovery links, no oEmbed JS provider.
	remove_action( 'wp_head', 'wp_oembed_add_discovery_links' );
	remove_action( 'wp_head', 'wp_oembed_add_host_js' );
	remove_action( 'wp_head', 'rest_output_link_wp_head' );
	remove_action( 'wp_head', 'wp_generator' );

	// Resource hints: no dns-prefetch / preconnect to external origins
	// (s.w.org and friends) - the store makes zero off-origin requests.
	remove_action( 'wp_head', 'wp_resource_hints', 2 );
}
add_action( 'init', 'urumi_store_disable_third_party' );

/**
 * Register the urumi-600 derivative (600px long side of the 4:5 grid crop) so
 * every sideloaded 1200px photo also ships a 600px derivative through srcset.
 * Also registers the primary nav menu location used by the header part. The
 * wp-setup job creates the "Primary" menu and assigns it.
 * Must run before the wp-setup seed sideloads images.
 */
function urumi_store_menus_and_sizes() {
	add_image_size( 'urumi-600', 600, 600, false );
	register_nav_menus(
		array(
			'primary' => __( 'Primary', 'urumi-store' ),
		)
	);
}

/**
 * Enqueue the theme stylesheet. The block theme's theme.json handles the base
 * styles; assets/styles.css carries everything blocks cannot express (nav,
 * hero overlay, tile hover, block cart/checkout restyle, focus, motion).
 */
function urumi_store_enqueue() {
	wp_enqueue_style(
		'urumi-store',
		get_stylesheet_directory_uri() . '/assets/styles.css',
		array(),
		URUMI_STORE_VERSION
	);
}
add_action( 'wp_enqueue_scripts', 'urumi_store_enqueue' );

/**
 * Preload the two fonts used above the fold on every page (serif display and
 * sans interface). font-display: swap is set in theme.json.
 */
function urumi_store_preloads() {
	$uri = get_stylesheet_directory_uri();
	echo '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . esc_url( $uri . '/assets/fonts/newsreader-latin-wght-normal.woff2' ) . '" />';
	echo '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . esc_url( $uri . '/assets/fonts/hanken-grotesk-latin-wght-normal.woff2' ) . '" />';
}
add_action( 'wp_head', 'urumi_store_preloads', 1 );

/**
 * Body classes: add the product-category term slug so taxonomy pages can be
 * selected in CSS without adding any colour per category (the new design keeps
 * every surface neutral).
 */
function urumi_store_body_class( $classes ) {
	if ( is_tax( 'product_cat' ) ) {
		$term = get_queried_object();
		if ( $term && isset( $term->slug ) ) {
			$classes[] = 'urumi-cat-' . sanitize_html_class( $term->slug );
		}
	}
	if ( is_product() ) {
		$product = wc_get_product( get_the_ID() );
		if ( $product ) {
			$terms = get_the_terms( $product->get_id(), 'product_cat' );
			if ( $terms && ! is_wp_error( $terms ) ) {
				$classes[] = 'urumi-cat-' . sanitize_html_class( $terms[0]->slug );
			}
		}
	}
	return $classes;
}
add_filter( 'body_class', 'urumi_store_body_class' );

/**
 * Is a product flagged as new? The seed mirrors products.json "new" into the
 * _urumi_is_new meta (distinct from Woo's featured flag since ADR-070).
 */
function urumi_store_product_is_new( $product ) {
	return $product instanceof WC_Product && '1' === get_post_meta( $product->get_id(), '_urumi_is_new', true );
}

/** Is a product on sale (simple sale price or any variation on sale)? */
function urumi_store_product_on_sale( $product ) {
	return $product instanceof WC_Product && $product->is_on_sale();
}

/** Is a product out of stock? */
function urumi_store_product_is_sold_out( $product ) {
	return $product instanceof WC_Product && ! $product->is_in_stock();
}

/** Price HTML for tiles: sale shows struck regular price; variable shows from. */
function urumi_store_tile_price_html( $product ) {
	if ( ! $product instanceof WC_Product ) {
		return '';
	}
	if ( $product->is_type( 'variable' ) ) {
		$prices = $product->get_variation_prices( true );
		$min = ! empty( $prices['price'] ) ? min( $prices['price'] ) : 0;
		return '<span class="urumi-tile__from">from</span> ' . esc_html( urumi_store_format_price( $min ) );
	}
	if ( $product->is_on_sale() && '' !== (string) $product->get_sale_price() ) {
		return '<del aria-hidden="true">' . esc_html( urumi_store_format_price( $product->get_regular_price() ) ) . '</del> '
			. '<span class="urumi-price--sale">' . esc_html( urumi_store_format_price( $product->get_price() ) ) . '</span>';
	}
	return esc_html( urumi_store_format_price( $product->get_price() ? $product->get_price() : $product->get_regular_price() ) );
}

/**
 * Tile flags: sale / new / sold out, one row, plain tracked text. Colour is
 * never the signal (STORE_DESIGN.md section 2).
 */
function urumi_store_tile_flags( $product ) {
	if ( ! $product instanceof WC_Product ) {
		return '';
	}
	$flags = '';
	if ( urumi_store_product_is_sold_out( $product ) ) {
		$flags .= '<span class="urumi-flag urumi-flag--oos">Sold out</span>';
	} elseif ( urumi_store_product_on_sale( $product ) ) {
		$flags .= '<span class="urumi-flag urumi-flag--sale">Sale</span>';
	}
	if ( urumi_store_product_is_new( $product ) ) {
		$flags .= '<span class="urumi-flag urumi-flag--new">New</span>';
	}
	return $flags ? '<span class="urumi-flags">' . $flags . '</span>' : '';
}

// ---------------------------------------------------------------------------
// Dynamic blocks
// ---------------------------------------------------------------------------

/** Photo frame: an <img> only when the file exists on disk, else a beige block. */
function urumi_store_photo_img( $file, $alt, $w, $h, $eager = false ) {
	$url = $file ? urumi_store_image_if_exists( $file ) : '';
	if ( '' === $url ) {
		return '<span class="urumi-photo urumi-photo--empty" aria-hidden="true"></span>';
	}
	return '<img class="urumi-photo" src="' . esc_url( $url ) . '" alt="' . esc_attr( $alt ) . '" loading="' . ( $eager ? 'eager' : 'lazy' ) . '" decoding="async" />';
}

function urumi_store_image_url_safe( $file ) {
	return urumi_store_asset_url( 'images/' . $file );
}

/**
 * Hero: one full-bleed lifestyle photograph with the warm 20 percent overlay,
 * a short Newsreader display headline and one outline button. The photo comes
 * from the catalog's "hero" entry (set during photo curation); without it the
 * hero falls back to a taupe block so the page never breaks.
 */
function urumi_store_hero_render() {
	$cat = urumi_store_catalog();
	$hero = $cat['hero'] ?? array();
	$headline = $hero['headline'] ?? 'Warm things for quiet rooms.';
	$sub = $hero['sub'] ?? 'Slow-made ceramics, textiles and desk goods. Ordered today, paid in cash when they arrive.';
	$file = $hero['image'] ?? '';
	$alt = $hero['alt'] ?? 'A quiet still life of ceramics and linen';

	$out = '<section class="urumi-hero" aria-labelledby="urumi-hero-title">';
	$out .= '<div class="urumi-hero__media" aria-hidden="false">';
	if ( $file && urumi_store_image_url( array( 'image' => $file ) ) && file_exists( urumi_store_data_dir() . '/images/' . $file ) ) {
		$out .= '<img class="urumi-photo" src="' . esc_url( urumi_store_asset_url( 'images/' . $file ) ) . '" alt="' . esc_attr( $alt ) . '" fetchpriority="high" decoding="async" />';
	} else {
		$out .= '<span class="urumi-photo urumi-photo--fallback" aria-hidden="true"></span>';
	}
	$out .= '<div class="urumi-hero__veil" aria-hidden="true"></div>';
	$out .= '</div>';
	$out .= '<div class="urumi-hero__text">';
	$out .= '<h1 id="urumi-hero-title" class="urumi-hero__title">' . esc_html( $headline ) . '</h1>';
	$out .= '<p class="urumi-hero__sub">' . esc_html( $sub ) . '</p>';
	$out .= '<a class="urumi-btn urumi-btn--outline urumi-btn--invert" href="' . esc_url( get_permalink( wc_get_page_id( 'shop' ) ) ) . '">Shop the collection</a>';
	$out .= '</div>';
	$out .= '</section>';
	return $out;
}
register_block_type( 'urumi-store/hero', array(
	'render_callback' => 'urumi_store_hero_render',
) );

/**
 * Category banner: one wide photograph at the top of a product-category
 * archive. The photo comes from the catalog category's "image"
 * (banner-<slug>.webp, set during photo curation); without it the archive
 * head renders exactly as before, so nothing breaks.
 */
function urumi_store_category_banner_render() {
	if ( ! is_tax( 'product_cat' ) ) {
		return '';
	}
	$term = get_queried_object();
	if ( ! $term || empty( $term->slug ) ) {
		return '';
	}
	$file = '';
	$alt = '';
	foreach ( urumi_store_catalog()['categories'] ?? array() as $c ) {
		if ( sanitize_title( $c['slug'] ?? '' ) === $term->slug ) {
			$file = (string) ( $c['image'] ?? '' );
			$alt = (string) ( $c['image_alt'] ?? $c['name'] );
			break;
		}
	}
	if ( '' === $file || ! file_exists( urumi_store_data_dir() . '/images/' . $file ) ) {
		return '';
	}
	return '<div class="urumi-cat-banner" aria-hidden="false">'
		. '<img class="urumi-photo" src="' . esc_url( urumi_store_asset_url( 'images/' . $file ) ) . '"'
		. ' alt="' . esc_attr( $alt ) . '" loading="eager" decoding="async" />'
		. '</div>';
}
register_block_type( 'urumi-store/category-banner', array(
	'render_callback' => 'urumi_store_category_banner_render',
) );

/**
 * Category tiles: six photo tiles in a 3 by 2 grid (2 by 3 on mobile). Each is
 * the category's first product photo; the category name sits below in
 * label-caps. Without photos the tile is a beige block.
 */
function urumi_store_categories_render() {
	$json = urumi_store_catalog();
	$cats = array();
	foreach ( $json['categories'] ?? array() as $c ) {
		$cats[ $c['slug'] ] = array(
			'name' => $c['name'],
			'count' => 0,
			'img' => '',
			'alt' => '',
		);
	}
	foreach ( $json['products'] ?? array() as $p ) {
		$slug = sanitize_title( $p['category'] ?? '' );
		if ( isset( $cats[ $slug ] ) ) {
			$cats[ $slug ]['count']++;
			if ( '' === $cats[ $slug ]['img'] && isset( $p['image'] ) ) {
				$cats[ $slug ]['img'] = $p['image'];
				$cats[ $slug ]['alt'] = $p['alt'] ?? $p['name'];
			}
		}
	}

	$out = '<div class="urumi-cat-grid" role="list">';
	foreach ( $cats as $slug => $c ) {
		$link = get_term_link( $slug, 'product_cat' );
		if ( is_wp_error( $link ) ) {
			$link = get_permalink( wc_get_page_id( 'shop' ) );
		}
		$out .= '<a class="urumi-cat-tile" href="' . esc_url( $link ) . '" role="listitem">';
		$out .= '<span class="urumi-cat-tile__media urumi-frame">';
		$out .= urumi_store_photo_img( $c['img'], $c['alt'] ? $c['alt'] : $c['name'], 480, 600 );
		$out .= '</span>';
		$out .= '<span class="urumi-cat-tile__label">' . esc_html( $c['name'] ) . '</span>';
		$out .= '</a>';
	}
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/categories', array(
	'render_callback' => 'urumi_store_categories_render',
) );

/**
 * NEW tag for the single-product template, rendered only when the current
 * product carries the catalog's new flag.
 */
function urumi_store_new_badge_render() {
	$product = wc_get_product( get_the_ID() );
	if ( ! $product || ! urumi_store_product_is_new( $product ) ) {
		return '';
	}
	return '<span class="urumi-flags"><span class="urumi-flag urumi-flag--new">New</span></span>';
}
register_block_type( 'urumi-store/new-badge', array(
	'render_callback' => 'urumi_store_new_badge_render',
) );

/**
 * Shared product tile markup for the grids (same DOM as the shop grid so one
 * stylesheet block styles all of them): 4:5 photo frame, name in Newsreader,
 * price in Hanken Grotesk. No card fill, no border, no radius.
 */
function urumi_store_tile( $product ) {
	$id = $product->get_id();
	$url = $product->get_permalink();
	$name = $product->get_name();

	$img = '';
	$img_id = $product->get_image_id();
	if ( $img_id ) {
		$img = wp_get_attachment_image( $img_id, 'large', false, array(
			'loading' => 'lazy',
			'decoding' => 'async',
			'class' => 'urumi-photo',
		) );
	} else {
		$img = '<span class="urumi-photo urumi-photo--empty" aria-hidden="true"></span>';
	}

	$flags = urumi_store_tile_flags( $product );

	$out = '<li class="urumi-tile' . ( urumi_store_product_is_sold_out( $product ) ? ' urumi-tile--oos' : '' ) . '" data-product-id="' . esc_attr( $id ) . '">';
	$out .= $flags;
	$out .= '<a class="urumi-tile__media urumi-frame" href="' . esc_url( $url ) . '" tabindex="-1" aria-hidden="true">' . $img . '</a>';
	$out .= '<a class="urumi-tile__name" href="' . esc_url( $url ) . '">' . esc_html( $name ) . '</a>';
	$out .= '<div class="urumi-tile__row">';
	$out .= '<span class="urumi-tile__price">' . urumi_store_tile_price_html( $product ) . '</span>';
	$out .= '<span class="urumi-tile__add">';
	if ( urumi_store_product_is_sold_out( $product ) ) {
		$out .= '<a class="urumi-btn-text" href="' . esc_url( $url ) . '">View</a>';
	} else {
		ob_start();
		woocommerce_template_loop_add_to_cart();
		$out .= ob_get_clean();
	}
	$out .= '</span>';
	$out .= '</div>';
	$out .= '</li>';
	return $out;
}

/**
 * Run a product query and render the shared tile grid. Shared by the featured
 * block.
 */
function urumi_store_render_grid( $args, $limit = 8 ) {
	$args = array_merge( array(
		'post_type'      => 'product',
		'post_status'    => 'publish',
		'posts_per_page' => $limit,
		'no_found_rows'  => true,
		'orderby'        => 'date',
		'order'          => 'DESC',
	), $args );
	$query = new WP_Query( $args );
	if ( ! $query->have_posts() ) {
		wp_reset_postdata();
		return '';
	}
	$out = '<ul class="urumi-grid urumi-grid--4">';
	while ( $query->have_posts() ) {
		$query->the_post();
		$product = wc_get_product( get_the_ID() );
		if ( $product ) {
			$out .= urumi_store_tile( $product );
		}
	}
	$out .= '</ul>';
	wp_reset_postdata();
	return $out;
}

/** Featured products grid (home "New and featured", 8 products). */
function urumi_store_featured_render() {
	return urumi_store_render_grid( array(
		'tax_query' => array(
			array(
				'taxonomy' => 'product_visibility',
				'field'    => 'name',
				'terms'    => 'featured',
			),
		),
	), 8 );
}
register_block_type( 'urumi-store/featured-grid', array(
	'render_callback' => 'urumi_store_featured_render',
) );

/**
 * Editorial split: one photograph on one side, a short materials-and-care text
 * block on the other, outline button. Photo comes from the catalog's
 * "editorial" entry; fallback is a beige block.
 */
function urumi_store_editorial_render() {
	$cat = urumi_store_catalog();
	$ed = $cat['editorial'] ?? array();
	$file = $ed['image'] ?? '';
	$alt = $ed['alt'] ?? 'Materials photograph';
	$heading = $ed['heading'] ?? 'Materials and care';
	$body = $ed['body'] ?? 'Every piece is photographed exactly as it is. Care notes ship with each order.';
	$button = $ed['button'] ?? 'Read the shop notes';
	$target = $ed['url'] ?? '/about/';
	$returns_page = get_page_by_path( 'about' );
	if ( $returns_page && '/about/' === $target ) {
		$target = get_permalink( $returns_page );
	}

	$out = '<div class="urumi-editorial urumi-band--alt">';
	$out .= '<div class="urumi-editorial__media urumi-frame">';
	$out .= urumi_store_photo_img( $file, $alt, 720, 900 );
	$out .= '</div>';
	$out .= '<div class="urumi-editorial__text">';
	$out .= '<h2 class="urumi-editorial__heading">' . esc_html( $heading ) . '</h2>';
	$out .= '<div class="urumi-editorial__body"><p>' . esc_html( $body ) . '</p></div>';
	$out .= '<a class="urumi-btn urumi-btn--outline" href="' . esc_url( $target ) . '">' . esc_html( $button ) . '</a>';
	$out .= '</div>';
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/editorial', array(
	'render_callback' => 'urumi_store_editorial_render',
) );

/**
 * Product meta line for the PDP: SKU and tags, so the page carries the full
 * catalog data.
 */
function urumi_store_product_meta_render() {
	$product = wc_get_product( get_the_ID() );
	if ( ! $product ) {
		return '';
	}
	$bits = array();
	if ( $product->get_sku() ) {
		$bits[] = 'SKU ' . $product->get_sku();
	}
	$terms = get_the_terms( $product->get_id(), 'product_tag' );
	if ( $terms && ! is_wp_error( $terms ) ) {
		$names = array();
		foreach ( $terms as $t ) {
			$names[] = $t->name;
		}
		if ( $names ) {
			$bits[] = 'Tagged ' . implode( ', ', $names );
		}
	}
	if ( ! $bits ) {
		return '';
	}
	return '<p class="urumi-pdp__meta">' . esc_html( implode( ' &middot; ', $bits ) ) . '</p>';
}
register_block_type( 'urumi-store/product-meta', array(
	'render_callback' => 'urumi_store_product_meta_render',
) );

// ---------------------------------------------------------------------------
// Grid flags + PDP stock line (block filters)
// ---------------------------------------------------------------------------

/**
 * Inject sale/new/sold-out flags into the WooCommerce product-image block used
 * by the shop / taxonomy / search grids. The collection loop sets up the global
 * post per product, so get_the_ID() is the product during render.
 */
function urumi_store_block_flags( $block_content, $block ) {
	if ( 'woocommerce/product-image' !== $block['blockName'] || ! $block_content ) {
		return $block_content;
	}
	$product = wc_get_product( get_the_ID() );
	$flags = $product ? urumi_store_tile_flags( $product ) : '';
	if ( ! $flags ) {
		return $block_content;
	}
	if ( urumi_store_product_is_sold_out( $product ) ) {
		$flags = str_replace( 'urumi-flags"', 'urumi-flags urumi-flags--oos"', $flags );
	}
	// The image block wrapper is positioned relative in CSS so the flags sit
	// in its top-left corner.
	return '<div class="urumi-flags-host">' . $flags . $block_content . '</div>';
}
add_filter( 'render_block', 'urumi_store_block_flags', 10, 2 );

/**
 * Stock state line above the add-to-cart form on the product page: honest,
 * plain-language availability. Words and weight only, never a colour signal.
 */
function urumi_store_stock_line( $block_content, $block ) {
	if ( 'woocommerce/add-to-cart-form' !== $block['blockName'] || ! $block_content ) {
		return $block_content;
	}
	$product = wc_get_product( get_the_ID() );
	if ( ! $product ) {
		return $block_content;
	}
	$line = '';
	if ( ! $product->is_in_stock() ) {
		$line = '<p class="urumi-stock urumi-stock--out">Sold out - back after the next batch.</p>';
	} elseif ( $product->is_type( 'variable' ) ) {
		$line = '<p class="urumi-stock">Choose an option to see availability.</p>';
	} elseif ( $product->get_manage_stock() && $product->get_stock_quantity() ) {
		$line = '<p class="urumi-stock urumi-stock--in">In stock - ' . intval( $product->get_stock_quantity() ) . ' ready to ship.</p>';
	} else {
		$line = '<p class="urumi-stock urumi-stock--in">In stock.</p>';
	}
	return $line . $block_content;
}
add_filter( 'render_block', 'urumi_store_stock_line', 10, 2 );

// ---------------------------------------------------------------------------
// Photography credits page (/image-credits/)
// ---------------------------------------------------------------------------

/**
 * Render the /image-credits/ page content from the committed manifest
 * (wp-content/store/photos-manifest.json, shipped in the store-assets image).
 * Honest empty state until photo curation fills the manifest (ADR-078).
 */
function urumi_store_credits_content( $content ) {
	if ( ! is_page( 'image-credits' ) ) {
		return $content;
	}
	$path = urumi_store_data_dir() . '/photos-manifest.json';
	$rows = '';
	if ( file_exists( $path ) ) {
		$json = wp_json_file_decode( $path, array( 'associative' => true ) );
		foreach ( ( $json['images'] ?? array() ) as $img ) {
			$rows .= '<tr><td>' . esc_html( $img['file'] ?? '' ) . '</td><td>' . esc_html( $img['sku'] ?? '' ) . '</td>'
				. '<td><a href="' . esc_url( $img['photographer_url'] ?? '#' ) . '">' . esc_html( $img['photographer'] ?? '' ) . '</a></td>'
				. '<td><a href="' . esc_url( $img['photo_url'] ?? '#' ) . '">Photo page</a></td>'
				. '<td>' . esc_html( $img['licence'] ?? 'Unsplash License' ) . '</td></tr>';
		}
	}
	$head = '<p>All photography on this demo storefront comes from Unsplash and is used under the <a href="https://unsplash.com/license">Unsplash License</a>. Each photographer is credited per file below.</p>';
	if ( '' === $rows ) {
		$head .= '<p>Per-photographer credits are being finalized; no photograph has been attached to the catalogue yet.</p>';
	} else {
		$head .= '<table class="urumi-credits"><thead><tr><th>File</th><th>SKU</th><th>Photographer</th><th>Photo</th><th>Licence</th></tr></thead><tbody>' . $rows . '</tbody></table>';
	}
	return $content . $head;
}
add_filter( 'the_content', 'urumi_store_credits_content' );

// ---------------------------------------------------------------------------
// Block patterns (the static sections of the front page)
// ---------------------------------------------------------------------------

function urumi_store_register_patterns() {
	$base = get_stylesheet_directory() . '/patterns';

	$patterns = array(
		'intro'        => array( 'title' => __( 'Intro statement', 'urumi-store' ) ),
		'new-featured' => array( 'title' => __( 'New and featured', 'urumi-store' ) ),
		'details-strip' => array( 'title' => __( 'Details strip', 'urumi-store' ) ),
	);
	foreach ( $patterns as $slug => $meta ) {
		$file = get_stylesheet_directory() . '/patterns/' . $slug . '.html';
		$content = file_exists( $file ) ? (string) file_get_contents( $file ) : '';
		if ( '' === $content ) {
			$content = '<!-- wp:paragraph --><p>' . esc_html( $meta['title'] ) . '</p><!-- /wp:paragraph -->';
		}
		register_block_pattern( 'urumi-store/' . $slug, array(
			'title'      => $meta['title'],
			'categories' => array( 'featured' ),
			'content'    => $content,
		) );
	}
}
add_action( 'init', 'urumi_store_register_patterns' );
