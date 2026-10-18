<?php
/**
 * Urumi Store theme bootstrap.
 *
 * Standalone block theme. This file wires:
 *  - a custom stylesheet (assets/styles.css) on top of theme.json
 *  - self-hosted font preloads (display font + hero image, nothing external)
 *  - removal of every third-party hook: emoji scripts, gravatars, oEmbed
 *  - dynamic blocks: urumi-store/hero, urumi-store/categories, urumi-store/new-badge
 *  - block patterns: new-in, split, faq, category-link (shop filters)
 *  - body classes for per-category tinting on the taxonomy pages
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'URUMI_STORE_VERSION', '1.0.0' );

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
function urumi_store_products() {
	static $products = null;
	if ( null !== $products ) {
		return $products;
	}
	$path = urumi_store_data_dir() . '/products.json';
	if ( ! file_exists( $path ) ) {
		$products = array();
		return $products;
	}
	$json = wp_json_file_decode( $path, array( 'associative' => true ) );
	$products = ( is_array( $json ) && isset( $json['products'] ) && is_array( $json['products'] ) ) ? $json['products'] : array();
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

/** Lowest price in products.json, formatted. */
function urumi_store_from_price() {
	$min = null;
	foreach ( urumi_store_products() as $p ) {
		if ( is_numeric( $p['price'] ) ) {
			$price = (float) $p['price'];
			$min = ( null === $min || $price < $min ) ? $price : $min;
		}
	}
	return urumi_store_format_price( $min ?? 0 );
}

/** URL to a store asset (image) inside wp-content/store. */
function urumi_store_asset_url( $path ) {
	return content_url( 'store/' . ltrim( $path, '/' ) );
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

	// Core only loads resources from this origin; nothing else to remove.
}
add_action( 'init', 'urumi_store_disable_third_party' );

/**
 * Enqueue the theme stylesheet. The block theme's theme.json handles the base
 * styles; assets/styles.css carries everything blocks cannot express (nav,
 * tile hover, block cart/checkout restyle, focus, motion).
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
 * Register the primary nav menu location. The wp-setup job creates the "Primary"
 * menu (Shop + categories) and assigns it here so Appearance > Menus reflects
 * the storefront navigation.
 */
function urumi_store_menus() {
	register_nav_menus(
		array(
			'primary' => __( 'Primary', 'urumi-store' ),
		)
	);
}
add_action( 'after_setup_theme', 'urumi_store_menus' );

/**
 * Preload the display font (used above the fold by every serif heading) and,
 * on the front page, the hero image. font-display: swap is set in theme.json.
 */
function urumi_store_preloads() {
	$uri = get_stylesheet_directory_uri();
	echo '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . esc_url( $uri . '/assets/fonts/instrument-serif-latin-400-normal.woff2' ) . '" />';
	if ( is_front_page() ) {
		echo '<link rel="preload" as="image" href="' . esc_url( urumi_store_asset_url( 'images/URUMI-HOODIE-001-cutout.png' ) ) . '" />';
	}
}
add_action( 'wp_head', 'urumi_store_preloads', 1 );

/**
 * Body classes: add the product-category term slug so taxonomy templates can
 * paint the tint behind the heading per category (CSS maps slug to tint).
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
 * Map a product category slug to its theme tint token slug. The mapping mirrors
 * store/products.json categories[].tint (Apparel periwinkle, Home peach,
 * Accessories lilac, Stationery sand).
 */
function urumi_store_tint_for_cat( $slug ) {
	$map = array(
		'apparel'     => 'periwinkle',
		'home'        => 'peach',
		'accessories' => 'lilac',
		'stationery'  => 'sand',
	);
	return isset( $map[ $slug ] ) ? $map[ $slug ] : 'periwinkle';
}

/**
 * Is a product flagged as new? The seeding job mirrors products.json "new" to
 * the WooCommerce featured flag, so featured == new on this store.
 */
function urumi_store_product_is_new( $product ) {
	return $product instanceof WC_Product && $product->get_featured();
}

// ---------------------------------------------------------------------------
// Dynamic blocks
// ---------------------------------------------------------------------------

/**
 * Hero: Dusk gradient container with soft grain, headline, copy, Shop now pill,
 * "from $X" computed from products.json, and the hoodie cut-out with a contact
 * shadow. The NEW tag renders only when the hero product is new (it is not).
 */
function urumi_store_hero_render() {
	$by_sku = urumi_store_products_by_sku();
	$hero = isset( $by_sku['URUMI-HOODIE-001'] ) ? $by_sku['URUMI-HOODIE-001'] : array();
	$hero_img = urumi_store_asset_url( 'images/' . ( isset( $hero['image'] ) ? str_replace( '.png', '-cutout.png', $hero['image'] ) : 'URUMI-HOODIE-001-cutout.png' ) );
	$hero_alt = isset( $hero['alt'] ) ? $hero['alt'] : 'Urumi Hoodie';

	// Soft grain: inline SVG turbulence (feTurbulence) - no external file.
	$noise = '<svg class="urumi-hero__noise" aria-hidden="true"><filter id="urumi-grain"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.045"/></feComponentTransfer></filter><rect width="100%" height="100%" filter="url(#urumi-grain)"/></svg>';

	$new_tag = '';
	if ( isset( $hero['new'] ) && $hero['new'] ) {
		$new_tag = '<span class="urumi-new-tag urumi-new-tag--outline">New</span>';
	}

	$headline = 'Good things, made simply.';
	$sub = 'A small catalog of everyday goods, made with care and shipped to you with cash on delivery.';
	$from = urumi_store_from_price();

	$out = '<section class="urumi-hero" aria-labelledby="urumi-hero-title">';
	$out .= '<div class="urumi-hero__bg" aria-hidden="true"></div>' . $noise;
	$out .= '<div class="urumi-hero__inner">';
	$out .= '<div class="urumi-hero__text">';
	$out .= $new_tag;
	$out .= '<h1 id="urumi-hero-title">' . esc_html( $headline ) . '</h1>';
	$out .= '<p class="urumi-hero__sub">' . esc_html( $sub ) . '</p>';
	$out .= '<div class="urumi-hero__actions">';
	$out .= '<a class="urumi-btn urumi-btn--ink" href="' . esc_url( get_permalink( wc_get_page_id( 'shop' ) ) ) . '">Shop now</a>';
	$out .= '<span class="urumi-hero__from">from ' . esc_html( $from ) . '</span>';
	$out .= '</div>';
	$out .= '</div>';
	$out .= '<div class="urumi-hero__art">';
	$out .= '<img class="urumi-hero__cutout" src="' . esc_url( $hero_img ) . '" alt="' . esc_attr( $hero_alt ) . '" width="960" height="960" loading="eager" decoding="async" />';
	$out .= '</div>';
	$out .= '</div>';
	$out .= '</section>';
	return $out;
}
register_block_type( 'urumi-store/hero', array(
	'render_callback' => 'urumi_store_hero_render',
) );

/**
 * Category tiles: four rounded tiles in their category tints with the cut-out,
 * label and product count (from products.json). Links to each category archive.
 */
function urumi_store_categories_render() {
	$json = urumi_store_products();
	$cats = array();
	foreach ( $json['categories'] ?? array() as $c ) {
		$cats[ $c['slug'] ] = array(
			'name' => $c['name'],
			'tint' => $c['tint'] ?? urumi_store_tint_for_cat( $c['slug'] ),
			'count' => 0,
			'img' => '',
		);
	}
	$by_sku = urumi_store_products_by_sku();
	foreach ( $json['products'] ?? array() as $p ) {
		$slug = sanitize_title( $p['category'] ?? '' );
		if ( isset( $cats[ $slug ] ) ) {
			$cats[ $slug ]['count']++;
			if ( '' === $cats[ $slug ]['img'] && isset( $p['image'] ) ) {
				$cats[ $slug ]['img'] = urumi_store_asset_url( 'images/' . str_replace( '.png', '-cutout.png', $p['image'] ) );
				$cats[ $slug ]['alt'] = $p['alt'] ?? $p['name'];
			}
		}
	}

	$out = '<div class="urumi-cat-grid" role="list">';
	foreach ( $cats as $slug => $c ) {
		$link = get_term_link( $slug, 'product_cat' );
		if ( is_wp_error( $link ) ) {
			$link = get_permalink( wc_get_page_id( 'shop' ) ) . '?product_cat=' . $slug;
		}
		$out .= '<a class="urumi-cat-tile urumi-tint--' . esc_attr( $c['tint'] ) . '" href="' . esc_url( $link ) . '" role="listitem">';
		$out .= '<span class="urumi-cat-tile__img">';
		if ( $c['img'] ) {
			$out .= '<img src="' . esc_url( $c['img'] ) . '" alt="' . esc_attr( $c['alt'] ?? $c['name'] ) . '" width="420" height="420" loading="lazy" decoding="async" />';
		}
		$out .= '</span>';
		$out .= '<span class="urumi-cat-tile__label">' . esc_html( $c['name'] ) . '</span>';
		$out .= '<span class="urumi-cat-tile__count">' . esc_html( $c['count'] ) . ( 1 === $c['count'] ? ' product' : ' products' ) . '</span>';
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
 * product is new (featured). The shop grid tiles get theirs from the pattern.
 */
function urumi_store_new_badge_render() {
	$product = wc_get_product( get_the_ID() );
	if ( ! $product || ! urumi_store_product_is_new( $product ) ) {
		return '';
	}
	return '<span class="urumi-new-tag">New</span>';
}
register_block_type( 'urumi-store/new-badge', array(
	'render_callback' => 'urumi_store_new_badge_render',
) );

/**
 * Shared product tile markup for the grids (same DOM as the shop grid so one
 * stylesheet block styles all of them): tile background, image, name,
 * descriptor line, price and an add-to-cart pill revealed on hover and focus.
 */
function urumi_store_tile( $product ) {
	$id = $product->get_id();
	$url = $product->get_permalink();
	$name = $product->get_name();
	$price = urumi_store_format_price( $product->get_price() ? $product->get_price() : $product->get_regular_price() );
	$desc = $product->get_short_description();

	$img = '';
	$img_id = $product->get_image_id();
	if ( $img_id ) {
		$img = wp_get_attachment_image( $img_id, 'full', false, array(
			'loading' => 'lazy',
			'decoding' => 'async',
		) );
	} else {
		$img = '<span class="urumi-tile__placeholder" aria-hidden="true"></span>';
	}

	$new = urumi_store_product_is_new( $product ) ? '<span class="urumi-new-tag">New</span>' : '';

	$out = '<li class="urumi-tile" data-product-id="' . esc_attr( $id ) . '">';
	$out .= '<a class="urumi-tile__media" href="' . esc_url( $url ) . '" tabindex="-1" aria-hidden="true">' . $img . '</a>';
	$out .= $new;
	$out .= '<a class="urumi-tile__name" href="' . esc_url( $url ) . '">' . esc_html( $name ) . '</a>';
	if ( $desc ) {
		$out .= '<p class="urumi-tile__desc">' . esc_html( $desc ) . '</p>';
	}
	$out .= '<div class="urumi-tile__row">';
	$out .= '<span class="urumi-tile__price">' . esc_html( $price ) . '</span>';
	$out .= '<span class="urumi-tile__add">';
	ob_start();
	woocommerce_template_loop_add_to_cart();
	$out .= ob_get_clean();
	$out .= '</span>';
	$out .= '</div>';
	$out .= '</li>';
	return $out;
}

/**
 * New in: the 8 most recent new (featured) products in the grid.
 */
function urumi_store_new_in_render() {
	$args = array(
		'post_type'      => 'product',
		'post_status'    => 'publish',
		'posts_per_page' => 8,
		'no_found_rows'  => true,
		'meta_key'       => '_featured',
		'meta_value'     => 'yes',
		'orderby'        => 'date',
		'order'          => 'DESC',
	);
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
register_block_type( 'urumi-store/new-in-grid', array(
	'render_callback' => 'urumi_store_new_in_render',
) );

/**
 * Split section: an illustrated panel (wool throw cut-out on a tint) and three
 * short true benefits. Cash on delivery and the returns page link are both
 * claims this storefront actually honours.
 */
function urumi_store_split_render() {
	$returns_page = get_page_by_path( 'shipping-and-returns' );
	$returns_url = $returns_page ? get_permalink( $returns_page ) : home_url( '/shipping-and-returns/' );

	$out = '<div class="urumi-split">';
	$out .= '<div class="urumi-split__panel">';
	$out .= '<img class="urumi-split__img" src="' . esc_url( urumi_store_asset_url( 'images/URUMI-THROW-001-cutout.png' ) ) . '" alt="Wool Throw" width="480" height="480" loading="lazy" decoding="async" />';
	$out .= '</div>';
	$out .= '<div class="urumi-split__text">';
	$out .= '<h2 class="urumi-section-title">Why shop with us</h2>';
	$out .= '<ul class="urumi-benefits">';
	$out .= '<li><strong>Cash on delivery</strong><span>Pay with cash when your order arrives.</span></li>';
	$out .= '<li><strong>Simple returns</strong><span>Read the <a href="' . esc_url( $returns_url ) . '">shipping and returns</a> policy before you buy.</span></li>';
	$out .= '<li><strong>Guest checkout</strong><span>Check out quickly without creating an account.</span></li>';
	$out .= '</ul>';
	$out .= '</div>';
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/split', array(
	'render_callback' => 'urumi_store_split_render',
) );

/**
 * FAQ accordions. Every answer matches the real policy pages (cash on delivery
 * only, no carrier integration, demo store).
 */
function urumi_store_faq_render() {
	$returns_page = get_page_by_path( 'shipping-and-returns' );
	$returns_url = $returns_page ? get_permalink( $returns_page ) : home_url( '/shipping-and-returns/' );

	$items = array(
		array(
			'q' => 'How do I pay?',
			'a' => 'We accept cash on delivery only. You pay in cash when your order arrives. No cards and no online payment.',
		),
		array(
			'q' => 'How long does delivery take?',
			'a' => 'This is a demo storefront with no carrier integration, so delivery times are illustrative only and orders are not fulfilled.',
		),
		array(
			'q' => 'Can I return an item?',
			'a' => 'Yes. Read the shipping and returns policy for the full process before you buy.',
		),
		array(
			'q' => 'Is this a real store?',
			'a' => 'No. This is a demo storefront for a school project. Orders are not fulfilled and payment is not collected.',
		),
	);

	$out = '<div class="urumi-faq">';
	$out .= '<h2 class="urumi-section-title">Frequently asked questions</h2>';
	$i = 0;
	foreach ( $items as $item ) {
		$i++;
		$out .= '<details class="urumi-faq__item" name="urumi-faq"><summary>' . esc_html( $item['q'] ) . '</summary><div class="urumi-faq__a">' . esc_html( $item['a'] ) . '</div></details>';
	}
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/faq', array(
	'render_callback' => 'urumi_store_faq_render',
) );

// ---------------------------------------------------------------------------
// Block patterns (the static sections of the front page)
// ---------------------------------------------------------------------------

function urumi_store_register_patterns() {
	$base = get_stylesheet_directory() . '/patterns';

	// New in: a product-collection query for featured (new) products, limit 8.
	$new_in = file_get_contents( $base . '/new-in.html' );
	register_block_pattern( 'urumi-store/new-in', array(
		'title'      => __( 'New in', 'urumi-store' ),
		'categories' => array( 'featured' ),
		'content'    => $new_in ? $new_in : '<!-- wp:paragraph --><p>New in</p><!-- /wp:paragraph -->',
	) );

	// Split: illustrated panel + three true benefits.
	$split = file_get_contents( $base . '/split.html' );
	register_block_pattern( 'urumi-store/split', array(
		'title'      => __( 'Why shop with us', 'urumi-store' ),
		'categories' => array( 'featured' ),
		'content'    => $split ? $split : '<!-- wp:paragraph --><p>Why shop with us</p><!-- /wp:paragraph -->',
	) );

	// FAQ accordions whose answers match the real policy pages.
	$faq = file_get_contents( $base . '/faq.html' );
	register_block_pattern( 'urumi-store/faq', array(
		'title'      => __( 'Frequently asked questions', 'urumi-store' ),
		'categories' => array( 'featured' ),
		'content'    => $faq ? $faq : '<!-- wp:paragraph --><p>FAQ</p><!-- /wp:paragraph -->',
	) );
}
add_action( 'init', 'urumi_store_register_patterns' );
