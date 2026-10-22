<?php
/**
 * Loam & Ember store theme bootstrap (store v2, ADR-070..074).
 *
 * Standalone block theme. This file wires:
 *  - the theme stylesheet (assets/styles.css) on top of theme.json
 *  - self-hosted font preloads (display font + dynamic hero cutout, no externals)
 *  - removal of every third-party hook: emoji scripts, gravatars, oEmbed
 *  - dynamic blocks: urumi-store/hero, urumi-store/categories, urumi-store/featured-grid,
 *    urumi-store/new-in-grid, urumi-store/new-badge, urumi-store/split, urumi-store/faq
 *  - tile flags (sale / new / sold out) injected into WooCommerce block grids
 *  - a stock-state line injected above the add-to-cart form on the product page
 *  - body classes for per-category tinting on the taxonomy pages
 *
 * The catalog (wp-content/store/products.json) is the single source of truth for
 * hero product, category tiles and tint mapping. "New" is the _urumi_is_new
 * product meta (set by the wp-setup seed); "featured" is Woo's featured flag.
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'URUMI_STORE_VERSION', '2.0.0' );
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

/** Lowest price in products.json, formatted. */
function urumi_store_from_price() {
	$min = null;
	foreach ( urumi_store_products() as $p ) {
		if ( isset( $p['price'] ) && is_numeric( $p['price'] ) ) {
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

/** Cutout URL for a catalog product entry. */
function urumi_store_cutout_url( $p ) {
	$name = isset( $p['image'] ) ? $p['image'] : ( $p['sku'] . '.png' );
	return urumi_store_asset_url( 'images/' . str_replace( '.png', '-cutout.png', $name ) );
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
 * menu (Shop + the six categories) and assigns it here.
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
 * on the front page, the hero cutout. font-display: swap is set in theme.json.
 */
function urumi_store_preloads() {
	$uri = get_stylesheet_directory_uri();
	echo '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . esc_url( $uri . '/assets/fonts/instrument-serif-latin-400-normal.woff2' ) . '" />';
	if ( is_front_page() ) {
		$hero = urumi_store_hero_product();
		if ( ! empty( $hero ) ) {
			echo '<link rel="preload" as="image" href="' . esc_url( urumi_store_cutout_url( $hero ) ) . '" />';
		}
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
 * Map a category slug to its tint, straight from products.json (single source
 * of truth). Falls back to sand when the slug is unknown.
 */
function urumi_store_tint_for_cat( $slug ) {
	foreach ( ( urumi_store_catalog()['categories'] ?? array() ) as $c ) {
		if ( ( $c['slug'] ?? '' ) === $slug ) {
			return $c['tint'] ?? 'sand';
		}
	}
	return 'sand';
}

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
 * Tile flags: sale / new / sold out, one row, colour never the only signal.
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

/** The hero product: the first featured catalog product, else the first one. */
function urumi_store_hero_product() {
	$by_sku = urumi_store_products_by_sku();
	foreach ( urumi_store_products() as $p ) {
		if ( ! empty( $p['featured'] ) && isset( $by_sku[ $p['sku'] ] ) ) {
			return $p;
		}
	}
	$first = urumi_store_products();
	return ! empty( $first ) ? $first[0] : array();
}

/**
 * Hero: Dusk gradient container with soft grain, headline, copy, Shop now pill,
 * "from $X" computed from products.json, and the featured product's cutout with
 * a contact shadow. The art links to the product page.
 */
function urumi_store_hero_render() {
	$hero = urumi_store_hero_product();
	if ( empty( $hero ) ) {
		return '';
	}
	$hero_img = urumi_store_cutout_url( $hero );
	$hero_alt = isset( $hero['alt'] ) ? $hero['alt'] : $hero['name'];
	$hero_url = get_permalink( wc_get_product_id_by_sku( $hero['sku'] ) ?: wc_get_page_id( 'shop' ) );

	// Soft grain: inline SVG turbulence (feTurbulence) - no external file.
	$noise = '<svg class="urumi-hero__noise" aria-hidden="true"><filter id="urumi-grain"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.045"/></feComponentTransfer></filter><rect width="100%" height="100%" filter="url(#urumi-grain)"/></svg>';

	$headline = 'Warm things for quiet rooms.';
	$sub = 'Slow-made ceramics, textiles and desk goods in small batches - ordered today, paid in cash when they arrive.';
	$from = urumi_store_from_price();

	$out = '<section class="urumi-hero" aria-labelledby="urumi-hero-title">';
	$out .= '<div class="urumi-hero__bg" aria-hidden="true"></div>' . $noise;
	$out .= '<div class="urumi-hero__inner">';
	$out .= '<div class="urumi-hero__text">';
	$out .= '<p class="urumi-hero__eyebrow">' . esc_html( URUMI_STORE_BRAND ) . '</p>';
	$out .= '<h1 id="urumi-hero-title">' . esc_html( $headline ) . '</h1>';
	$out .= '<p class="urumi-hero__sub">' . esc_html( $sub ) . '</p>';
	$out .= '<div class="urumi-hero__actions">';
	$out .= '<a class="urumi-btn urumi-btn--ink" href="' . esc_url( get_permalink( wc_get_page_id( 'shop' ) ) ) . '">Shop now</a>';
	$out .= '<span class="urumi-hero__from">from ' . esc_html( $from ) . '</span>';
	$out .= '</div>';
	$out .= '</div>';
	$out .= '<div class="urumi-hero__art">';
	$out .= '<a href="' . esc_url( $hero_url ) . '" aria-label="Shop ' . esc_attr( $hero['name'] ) . '">';
	$out .= '<img class="urumi-hero__cutout" src="' . esc_url( $hero_img ) . '" alt="' . esc_attr( $hero_alt ) . '" width="960" height="960" loading="eager" decoding="async" />';
	$out .= '</a>';
	$out .= '<span class="urumi-hero__caption">' . esc_html( $hero['name'] ) . '</span>';
	$out .= '</div>';
	$out .= '</div>';
	$out .= '</section>';
	return $out;
}
register_block_type( 'urumi-store/hero', array(
	'render_callback' => 'urumi_store_hero_render',
) );

/**
 * Category tiles: six rounded tiles in their category tints with the cutout of
 * the category's first product, label and product count (from products.json).
 */
function urumi_store_categories_render() {
	$json = urumi_store_catalog();
	$cats = array();
	foreach ( $json['categories'] ?? array() as $c ) {
		$cats[ $c['slug'] ] = array(
			'name' => $c['name'],
			'tint' => $c['tint'] ?? 'sand',
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
				$cats[ $slug ]['img'] = urumi_store_cutout_url( $p );
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
		$out .= '<a class="urumi-cat-tile urumi-tint--' . esc_attr( $c['tint'] ) . '" href="' . esc_url( $link ) . '" role="listitem">';
		$out .= '<span class="urumi-cat-tile__img">';
		if ( $c['img'] ) {
			$out .= '<img src="' . esc_url( $c['img'] ) . '" alt="' . esc_attr( $c['alt'] ?: $c['name'] ) . '" width="420" height="420" loading="lazy" decoding="async" />';
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
 * stylesheet block styles all of them): tile background, image, name,
 * descriptor line, price and an add-to-cart pill revealed on hover and focus.
 */
function urumi_store_tile( $product ) {
	$id = $product->get_id();
	$url = $product->get_permalink();
	$name = $product->get_name();
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

	$flags = urumi_store_tile_flags( $product );

	$out = '<li class="urumi-tile' . ( urumi_store_product_is_sold_out( $product ) ? ' urumi-tile--oos' : '' ) . '" data-product-id="' . esc_attr( $id ) . '">';
	$out .= $flags;
	$out .= '<a class="urumi-tile__media" href="' . esc_url( $url ) . '" tabindex="-1" aria-hidden="true">' . $img . '</a>';
	$out .= '<a class="urumi-tile__name" href="' . esc_url( $url ) . '">' . esc_html( $name ) . '</a>';
	if ( $desc ) {
		$out .= '<p class="urumi-tile__desc">' . esc_html( wp_strip_all_tags( $desc ) ) . '</p>';
	}
	$out .= '<div class="urumi-tile__row">';
	$out .= '<span class="urumi-tile__price">' . urumi_store_tile_price_html( $product ) . '</span>';
	$out .= '<span class="urumi-tile__add">';
	if ( urumi_store_product_is_sold_out( $product ) ) {
		$out .= '<a class="urumi-pill-btn" href="' . esc_url( $url ) . '">View</a>';
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
 * and new-in blocks.
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

/** Featured products grid (home "Featured"). */
function urumi_store_featured_render() {
	return urumi_store_render_grid( array(
		'tax_query' => array(
			array(
				'taxonomy' => 'product_visibility',
				'field'    => 'name',
				'terms'    => 'featured',
			),
		),
	), 6 );
}
register_block_type( 'urumi-store/featured-grid', array(
	'render_callback' => 'urumi_store_featured_render',
) );

/**
 * New in: the 8 most recent products carrying the catalog's new flag.
 */
function urumi_store_new_in_render() {
	return urumi_store_render_grid( array(
		'meta_query' => array(
			array(
				'key'   => '_urumi_is_new',
				'value' => '1',
			),
		),
	), 8 );
}
register_block_type( 'urumi-store/new-in-grid', array(
	'render_callback' => 'urumi_store_new_in_render',
) );

/**
 * Split section: an illustrated panel (a catalog product's cutout on a tint)
 * and three short true benefits. Cash on delivery and the returns page link
 * are both claims this storefront actually honours.
 */
function urumi_store_split_render() {
	$returns_page = get_page_by_path( 'shipping-and-returns' );
	$returns_url = $returns_page ? get_permalink( $returns_page ) : home_url( '/shipping-and-returns/' );

	$by_sku = urumi_store_products_by_sku();
	$p = isset( $by_sku['LOAM-TEX-001'] ) ? $by_sku['LOAM-TEX-001'] : ( urumi_store_products() ? urumi_store_products()[0] : array() );
	$img = ! empty( $p ) ? urumi_store_cutout_url( $p ) : '';
	$alt = ! empty( $p['alt'] ) ? $p['alt'] : 'Wool Throw';

	$out = '<div class="urumi-split">';
	$out .= '<div class="urumi-split__panel urumi-tint--lilac">';
	if ( $img ) {
		$out .= '<img class="urumi-split__img" src="' . esc_url( $img ) . '" alt="' . esc_attr( $alt ) . '" width="480" height="480" loading="lazy" decoding="async" />';
	}
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
			'a' => 'No. Loam & Ember is a fictional demo storefront for a school project. Orders are not fulfilled and payment is not collected.',
		),
	);

	$out = '<div class="urumi-faq">';
	$out .= '<h2 class="urumi-section-title">Frequently asked questions</h2>';
	foreach ( $items as $item ) {
		$out .= '<details class="urumi-faq__item" name="urumi-faq"><summary>' . esc_html( $item['q'] ) . '</summary><div class="urumi-faq__a">' . esc_html( $item['a'] ) . '</div></details>';
	}
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/faq', array(
	'render_callback' => 'urumi_store_faq_render',
) );

/**
 * Product meta line for the PDP: SKU, tags and category, so the page carries
 * the full catalog data (ADR-070).
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
 * plain-language availability (manage-stock quantity when tracked).
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
		$line = '<p class="urumi-stock urumi-stock--out">Out of stock - back after the next batch.</p>';
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
// Block patterns (the static sections of the front page)
// ---------------------------------------------------------------------------

function urumi_store_register_patterns() {
	$base = get_stylesheet_directory() . '/patterns';

	$patterns = array(
		'new-in'     => array( 'title' => __( 'New in', 'urumi-store' ) ),
		'trust'      => array( 'title' => __( 'Trust strip', 'urumi-store' ) ),
		'newsletter' => array( 'title' => __( 'Newsletter', 'urumi-store' ) ),
		'split'      => array( 'title' => __( 'Why shop with us', 'urumi-store' ) ),
		'faq'        => array( 'title' => __( 'Frequently asked questions', 'urumi-store' ) ),
	);
	foreach ( $patterns as $slug => $meta ) {
		$file = $base . '/' . $slug . '.html';
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
