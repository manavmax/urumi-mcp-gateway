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
 * Enqueue the theme stylesheet and the small vanilla JS for the storefront
 * (search suggestions, mobile sticky add-to-cart, filter form guards). The
 * block theme's theme.json handles the base styles; assets/styles.css carries
 * everything blocks cannot express (nav, hero overlay, tile hover, block
 * cart/checkout restyle, focus, motion).
 */
function urumi_store_enqueue() {
	wp_enqueue_style(
		'urumi-store',
		get_stylesheet_directory_uri() . '/assets/styles.css',
		array(),
		URUMI_STORE_VERSION
	);
	wp_enqueue_script(
		'urumi-store-js',
		get_stylesheet_directory_uri() . '/assets/store.js',
		array(),
		URUMI_STORE_VERSION,
		true
	);
}
add_action( 'wp_enqueue_scripts', 'urumi_store_enqueue' );

/**
 * Cart and checkout blocks (mini-cart drawer, block cart, block checkout) read
 * their data from the Store API, and every URL generated inside /wp-json/ uses
 * https because the urumi-internal-rest mu-plugin marks REST requests as SSL
 * (so in-cluster Basic auth works over plain HTTP). When the request itself
 * arrived over plain HTTP through the ingress, that makes product thumbnails
 * and other links in the JSON unusable in the browser (no TLS on the local
 * ingress). Rewrite same-host https URLs to http for those responses only;
 * production (TLS) and in-cluster callers (no forwarded proto) are untouched.
 */
function urumi_store_rest_scheme_walk( &$data, $host ) {
	if ( is_string( $data ) ) {
		$from = 'https://' . $host;
		$to = 'http://' . $host;
		if ( 0 === strpos( $data, $from ) ) {
			$data = substr_replace( $data, $to, 0, strlen( $from ) );
		}
		return;
	}
	if ( is_array( $data ) ) {
		foreach ( $data as &$value ) {
			urumi_store_rest_scheme_walk( $value, $host );
		}
		return;
	}
	if ( is_object( $data ) ) {
		foreach ( $data as $key => $value ) {
			urumi_store_rest_scheme_walk( $data->$key, $host );
		}
	}
}

function urumi_store_rest_scheme( $result, $request, $server ) {
	$proto = isset( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) ? strtolower( strtok( (string) wp_unslash( $_SERVER['HTTP_X_FORWARDED_PROTO'] ), ',' ) ) : '';
	if ( 'http' !== $proto || empty( $result ) ) {
		return $result;
	}
	$host = wp_parse_url( home_url(), PHP_URL_HOST );
	if ( ! $host ) {
		return $result;
	}
	urumi_store_rest_scheme_walk( $result, $host );
	return $result;
}
add_filter( 'rest_pre_echo_response', 'urumi_store_rest_scheme', 10, 3 );

/**
 * Catalog sorting: keep only the honest options. Popularity (seeded sales
 * figures) and rating (no reviews exist) would mislead; keep the shop order,
 * newest and both price directions, with plain labels.
 */
function urumi_store_catalog_orderby( $options ) {
	unset( $options['popularity'], $options['rating'] );
	if ( isset( $options['date'] ) ) {
		$options['date'] = __( 'Newest first', 'urumi-store' );
	}
	return $options;
}
add_filter( 'woocommerce_catalog_orderby', 'urumi_store_catalog_orderby' );

/**
 * Drop empty min_price/max_price arguments before WooCommerce reads them so
 * the price filter form never narrows the grid to nothing when a field is
 * submitted blank (Woo core treats an empty max_price as 0).
 */
function urumi_store_price_query_guard( $query ) {
	if ( ! $query->is_main_query() ) {
		return;
	}
	foreach ( array( 'min_price', 'max_price' ) as $key ) {
		if ( isset( $_GET[ $key ] ) && '' === trim( (string) wp_unslash( $_GET[ $key ] ) ) ) {
			unset( $_GET[ $key ] );
		}
	}
}
add_action( 'pre_get_posts', 'urumi_store_price_query_guard', 9 );

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
// Navigation, filters and related products (shopping-flow polish)
// ---------------------------------------------------------------------------

/**
 * Category links in the catalog's own order (ceramics first, carry last). The
 * order comes from products.json so the nav matches the designed catalogue,
 * not the alphabetical term order.
 */
function urumi_store_category_links() {
	$links = array();
	$catalog_slugs = array();
	foreach ( urumi_store_catalog()['categories'] ?? array() as $c ) {
		if ( ! empty( $c['slug'] ) ) {
			$catalog_slugs[] = sanitize_title( $c['slug'] );
		}
	}
	$by_slug = array();
	$terms = get_terms( array(
		'taxonomy'   => 'product_cat',
		'hide_empty' => false,
	) );
	if ( is_wp_error( $terms ) ) {
		return $links;
	}
	foreach ( $terms as $term ) {
		// Dead terms from older seed runs (empty categories) never appear in
		// the nav: a link must lead to products. A term is kept when it is in
		// the current catalogue or still has published products.
		if ( 'uncategorized' === $term->slug || $term->count < 1 ) {
			continue;
		}
		$by_slug[ $term->slug ] = $term;
	}
	foreach ( $catalog_slugs as $slug ) {
		if ( isset( $by_slug[ $slug ] ) ) {
			$links[ $slug ] = array(
				'name' => $by_slug[ $slug ]->name,
				'url'  => get_term_link( $by_slug[ $slug ], 'product_cat' ),
			);
			unset( $by_slug[ $slug ] );
		}
	}
	foreach ( $by_slug as $slug => $term ) {
		$links[ $slug ] = array(
			'name' => $term->name,
			'url'  => get_term_link( $term, 'product_cat' ),
		);
	}
	return $links;
}

/**
 * Static page links for the nav (only when the page exists).
 */
function urumi_store_page_links() {
	$out = array();
	foreach ( array( 'about' => 'About', 'shipping-and-returns' => 'Shipping and returns' ) as $path => $label ) {
		$page = get_page_by_path( $path );
		if ( $page ) {
			$out[] = array( 'name' => $label, 'url' => get_permalink( $page ) );
		}
	}
	return $out;
}

/**
 * Items of the theme-registered 'primary' menu, but only when every link
 * still resolves (the seeded menu predates the current catalogue and carries
 * dead category links; a stale menu is never shown - the taxonomy fallback
 * is used instead). Custom-item URLs are checked against the live shop,
 * categories, products and the static pages.
 */
function urumi_store_validated_menu_items() {
	$locations = get_nav_menu_locations();
	if ( empty( $locations['primary'] ) ) {
		return null;
	}
	$menu = wp_get_nav_menu_object( $locations['primary'] );
	if ( ! $menu ) {
		return null;
	}
	$items = wp_get_nav_menu_items( $menu->term_id );
	if ( ! $items ) {
		return null;
	}
	$cat_slugs = array();
	foreach ( urumi_store_category_links() as $slug => $link ) {
		$cat_slugs[] = $slug;
	}
	$out = array();
	foreach ( $items as $item ) {
		$url = $item->url;
		$ok = false;
		if ( 0 === strpos( $url, home_url() ) ) {
			$path = trim( (string) wp_parse_url( $url, PHP_URL_PATH ), '/' );
			if ( '' === $path || 'shop' === $path || 'cart' === $path || 'checkout' === $path || 'my-account' === $path ) {
				$ok = true;
			} elseif ( 0 === strpos( $path, 'product-category/' ) ) {
				$ok = in_array( substr( $path, strlen( 'product-category/' ) ), $cat_slugs, true );
			} elseif ( 0 === strpos( $path, 'product/' ) ) {
				$ok = (bool) get_page_by_path( $path, OBJECT, 'product' );
			} elseif ( in_array( $path, array( 'about', 'shipping-and-returns', 'image-credits', 'privacy-policy', 'terms' ), true ) ) {
				$ok = (bool) get_page_by_path( $path );
			}
		}
		if ( ! $ok ) {
			return null;
		}
		$out[] = array( 'name' => $item->title, 'url' => $url );
	}
	return $out;
}

/**
 * Category navigation block. Desktop: Shop, a Collections dropdown with the
 * product categories, then the static pages. Overlay: a flat link list for
 * the mobile menu. The theme-registered 'primary' menu is used when all of
 * its links resolve; otherwise the nav is built from the live product
 * categories, so it can never show a dead link.
 */
function urumi_store_category_nav_render( $attributes ) {
	$variant = isset( $attributes['variant'] ) ? (string) $attributes['variant'] : 'desktop';
	$shop = array( 'name' => 'Shop', 'url' => get_permalink( wc_get_page_id( 'shop' ) ) );

	if ( 'pills' === $variant ) {
		$current = '';
		if ( is_tax( 'product_cat' ) ) {
			$term = get_queried_object();
			if ( $term && isset( $term->slug ) ) {
				$current = $term->slug;
			}
		}
		$out = '<div class="urumi-filter-pills" role="navigation" aria-label="Shop by category">';
		$all_current = ( is_shop() && ! is_search() ) ? ' aria-current="page"' : '';
		$out .= '<a class="urumi-pill urumi-pill--all"' . $all_current . ' data-cat="all" href="' . esc_url( $shop['url'] ) . '">All</a>';
		foreach ( urumi_store_category_links() as $slug => $link ) {
			$cur = ( $slug === $current ) ? ' aria-current="page"' : '';
			$out .= '<a class="urumi-pill"' . $cur . ' data-cat="' . esc_attr( $slug ) . '" href="' . esc_url( $link['url'] ) . '">' . esc_html( $link['name'] ) . '</a>';
		}
		$out .= '</div>';
		return $out;
	}

	if ( 'overlay' === $variant ) {
		$out = '<a href="' . esc_url( $shop['url'] ) . '">Shop</a>';
		foreach ( urumi_store_category_links() as $link ) {
			$out .= '<a href="' . esc_url( $link['url'] ) . '">' . esc_html( $link['name'] ) . '</a>';
		}
		foreach ( urumi_store_page_links() as $link ) {
			$out .= '<a href="' . esc_url( $link['url'] ) . '">' . esc_html( $link['name'] ) . '</a>';
		}
		return $out;
	}

	$menu_items = urumi_store_validated_menu_items();
	if ( is_array( $menu_items ) ) {
		$out = '<nav class="urumi-nav__links" aria-label="Primary">';
		foreach ( $menu_items as $item ) {
			$out .= '<a href="' . esc_url( $item['url'] ) . '">' . esc_html( $item['name'] ) . '</a>';
		}
		$out .= '</nav>';
		return $out;
	}

	$out = '<nav class="urumi-nav__links" aria-label="Primary">';
	$out .= '<a href="' . esc_url( $shop['url'] ) . '">Shop</a>';
	$cats = urumi_store_category_links();
	if ( $cats ) {
		$out .= '<details class="urumi-nav__dropdown">';
		$out .= '<summary>Collections</summary>';
		$out .= '<div class="urumi-nav__dropdown-menu">';
		foreach ( $cats as $link ) {
			$out .= '<a href="' . esc_url( $link['url'] ) . '">' . esc_html( $link['name'] ) . '</a>';
		}
		$out .= '</div>';
		$out .= '</details>';
	}
	foreach ( urumi_store_page_links() as $link ) {
		$out .= '<a href="' . esc_url( $link['url'] ) . '">' . esc_html( $link['name'] ) . '</a>';
	}
	$out .= '</nav>';
	return $out;
}
register_block_type( 'urumi-store/category-nav', array(
	'render_callback' => 'urumi_store_category_nav_render',
) );

/**
 * Catalogue price bounds (sale price wins), from products.json - the single
 * source of truth for the demo catalogue.
 */
function urumi_store_price_bounds() {
	$prices = array();
	foreach ( urumi_store_products() as $p ) {
		$price = isset( $p['sale_price'] ) && is_numeric( $p['sale_price'] ) && (float) $p['sale_price'] > 0 ? (float) $p['sale_price'] : ( ( isset( $p['price'] ) && is_numeric( $p['price'] ) ) ? (float) $p['price'] : 0 );
		if ( $price > 0 ) {
			$prices[] = $price;
		}
	}
	if ( ! $prices ) {
		return null;
	}
	return array( min( $prices ), max( $prices ) );
}

/**
 * The current archive URL without filter query arguments, keeping the sort if
 * one is active.
 */
function urumi_store_archive_base_url( $keep_orderby = true ) {
	$url = '';
	if ( is_product_taxonomy() ) {
		$term = get_queried_object();
		if ( $term && isset( $term->slug ) ) {
			$url = get_term_link( $term, 'product_cat' );
		}
	}
	if ( ! $url || is_wp_error( $url ) ) {
		$url = get_permalink( wc_get_page_id( 'shop' ) );
	}
	if ( $keep_orderby && isset( $_GET['orderby'] ) && in_array( (string) wp_unslash( $_GET['orderby'] ), array( 'menu_order', 'date', 'price', 'price-desc' ), true ) ) {
		$url = add_query_arg( 'orderby', (string) wp_unslash( $_GET['orderby'] ), $url );
	}
	return $url;
}

/**
 * Price filter block: a compact GET form with min and max price fields, plus
 * the catalogue's real price range as a hint. WooCommerce core applies
 * min_price/max_price to the archive query, so this works with the
 * product-collection block and needs no JavaScript to filter.
 */
function urumi_store_price_filter_render() {
	if ( ! ( is_shop() || is_product_taxonomy() ) ) {
		return '';
	}
	$bounds = urumi_store_price_bounds();
	if ( ! $bounds ) {
		return '';
	}
	$min = isset( $_GET['min_price'] ) && is_numeric( wp_unslash( $_GET['min_price'] ) ) ? (string) wp_unslash( $_GET['min_price'] ) : '';
	$max = isset( $_GET['max_price'] ) && is_numeric( wp_unslash( $_GET['max_price'] ) ) ? (string) wp_unslash( $_GET['max_price'] ) : '';
	$out = '<form class="urumi-price-filter" method="get" action="' . esc_url( urumi_store_archive_base_url() ) . '" data-urumi-price-filter>';
	$out .= '<span class="urumi-price-filter__label" id="urumi-price-filter-label">Price $' . number_format( $bounds[0], 0 ) . '&ndash;$' . number_format( $bounds[1], 0 ) . '</span>';
	$out .= '<span class="urumi-price-filter__fields">';
	$out .= '<label class="urumi-search-label" for="urumi-min-price">Minimum price</label>';
	$out .= '<input id="urumi-min-price" name="min_price" type="number" inputmode="numeric" min="0" step="1" placeholder="' . number_format( $bounds[0], 0 ) . '" value="' . esc_attr( $min ) . '" aria-describedby="urumi-price-filter-label" />';
	$out .= '<label class="urumi-search-label" for="urumi-max-price">Maximum price</label>';
	$out .= '<input id="urumi-max-price" name="max_price" type="number" inputmode="numeric" min="0" step="1" placeholder="' . number_format( $bounds[1], 0 ) . '" value="' . esc_attr( $max ) . '" aria-describedby="urumi-price-filter-label" />';
	$out .= '<button class="urumi-btn urumi-btn--outline urumi-price-filter__apply" type="submit">Filter</button>';
	$out .= '</span>';
	$out .= '</form>';
	return $out;
}
register_block_type( 'urumi-store/price-filter', array(
	'render_callback' => 'urumi_store_price_filter_render',
) );

/**
 * Active filter chips: one removable chip per active filter (category, price
 * range, search term) so it is always clear why the grid shows what it shows.
 * Renders nothing when no filter is active.
 */
function urumi_store_active_filters_render() {
	$chips = array();
	if ( is_product_taxonomy() ) {
		$term = get_queried_object();
		if ( $term && isset( $term->name ) ) {
			$chips[] = array(
				'label' => $term->name,
				'url'   => urumi_store_archive_base_url(),
			);
		}
	}
	$min = isset( $_GET['min_price'] ) && is_numeric( wp_unslash( $_GET['min_price'] ) ) ? (float) wp_unslash( $_GET['min_price'] ) : null;
	$max = isset( $_GET['max_price'] ) && is_numeric( wp_unslash( $_GET['max_price'] ) ) ? (float) wp_unslash( $_GET['max_price'] ) : null;
	if ( null !== $min || null !== $max ) {
		$label = 'Price ';
		$label .= null !== $min ? '$' . number_format( $min, 0 ) : '';
		$label .= ( null !== $min && null !== $max ) ? '&ndash;' : ( null !== $min ? '+' : ' up to ' );
		$label .= null !== $max ? '$' . number_format( $max, 0 ) : '';
		$url = urumi_store_archive_base_url();
		$chips[] = array( 'label' => $label, 'url' => $url );
	}
	if ( is_search() ) {
		$chips[] = array(
			'label' => '&ldquo;' . esc_html( get_search_query() ) . '&rdquo;',
			'url'   => get_permalink( wc_get_page_id( 'shop' ) ),
		);
	}
	if ( ! $chips ) {
		return '';
	}
	$out = '<div class="urumi-active-filters" role="list" aria-label="Active filters">';
	foreach ( $chips as $chip ) {
		$out .= '<a class="urumi-chip" role="listitem" href="' . esc_url( $chip['url'] ) . '">';
		$out .= '<span class="urumi-chip__label">' . wp_kses( $chip['label'], array() ) . '</span>';
		$out .= '<span class="urumi-chip__x" aria-hidden="true">&times;</span>';
		$out .= '<span class="urumi-search-label">Remove filter ' . wp_strip_all_tags( $chip['label'] ) . '</span>';
		$out .= '</a>';
	}
	if ( count( $chips ) > 1 ) {
		$out .= '<a class="urumi-chip urumi-chip--clear" role="listitem" href="' . esc_url( urumi_store_archive_base_url( false ) ) . '">Clear all</a>';
	}
	$out .= '</div>';
	return $out;
}
register_block_type( 'urumi-store/active-filters', array(
	'render_callback' => 'urumi_store_active_filters_render',
) );

/**
 * Related products from the same category as the current product, excluding
 * the product itself. Four tiles (two on mobile) in the shared grid markup.
 */
function urumi_store_related_render() {
	$product = wc_get_product( get_the_ID() );
	if ( ! $product ) {
		return '';
	}
	$terms = get_the_terms( $product->get_id(), 'product_cat' );
	if ( ! $terms || is_wp_error( $terms ) ) {
		return '';
	}
	$grid = urumi_store_render_grid( array(
		'tax_query' => array(
			array(
				'taxonomy' => 'product_cat',
				'field'    => 'term_id',
				'terms'    => wp_list_pluck( $terms, 'term_id' ),
			),
		),
		'post__not_in' => array( $product->get_id() ),
		'orderby'      => 'title',
		'order'        => 'ASC',
	), 4 );
	if ( '' === $grid ) {
		return '';
	}
	$shop = get_permalink( wc_get_page_id( 'shop' ) );
	$out = '<section class="urumi-related" aria-labelledby="urumi-related-title">';
	$out .= '<div class="urumi-related__head"><h2 id="urumi-related-title" class="urumi-section-title">You may also like</h2>';
	$out .= '<a class="urumi-btn-text" href="' . esc_url( $shop ) . '">View all</a></div>';
	$out .= $grid;
	$out .= '</section>';
	return $out;
}
register_block_type( 'urumi-store/related', array(
	'render_callback' => 'urumi_store_related_render',
) );

/**
 * Sticky add-to-cart bar for mobile product pages: product name, price and a
 * one-tap add (simple products) or a jump to the options form (variable or
 * out-of-stock). The bar is hidden until the main add-to-cart form scrolls
 * out of view; assets/store.js toggles it.
 */
function urumi_store_sticky_atc_render() {
	if ( ! is_product() ) {
		return '';
	}
	$product = wc_get_product( get_the_ID() );
	if ( ! $product ) {
		return '';
	}
	$id = $product->get_id();
	$name = $product->get_name();
	if ( $product->is_type( 'variable' ) ) {
		$prices = $product->get_variation_prices( true );
		$min = ! empty( $prices['price'] ) ? min( $prices['price'] ) : 0;
		$price = '<span class="urumi-tile__from">from</span> ' . esc_html( urumi_store_format_price( $min ) );
		$action = '<a class="urumi-btn urumi-btn--outline" href="#urumi-pdp-form">Choose options</a>';
	} elseif ( $product->is_on_sale() && '' !== (string) $product->get_sale_price() ) {
		$price = '<del aria-hidden="true">' . esc_html( urumi_store_format_price( $product->get_regular_price() ) ) . '</del> ' . esc_html( urumi_store_format_price( $product->get_sale_price() ) );
		$action = urumi_store_sticky_atc_form( $id );
	} else {
		$price = esc_html( urumi_store_format_price( $product->get_price() ? $product->get_price() : $product->get_regular_price() ) );
		$action = urumi_store_sticky_atc_form( $id );
	}
	if ( ! $product->is_in_stock() ) {
		$price = esc_html( urumi_store_format_price( $product->get_regular_price() ) );
		$action = '<a class="urumi-btn urumi-btn--outline" href="#urumi-pdp-form">View details</a>';
	}
	$out = '<div class="urumi-sticky-atc" data-urumi-sticky-atc hidden>';
	$out .= '<span class="urumi-sticky-atc__name">' . esc_html( $name ) . '</span>';
	$out .= '<span class="urumi-sticky-atc__price">' . $price . '</span>';
	$out .= '<span class="urumi-sticky-atc__action">' . $action . '</span>';
	$out .= '</div>';
	return $out;
}

function urumi_store_sticky_atc_form( $id ) {
	return '<form class="urumi-sticky-atc__form" method="get" action="' . esc_url( get_permalink( $id ) ) . '">'
		. '<input type="hidden" name="add-to-cart" value="' . esc_attr( $id ) . '" />'
		. '<input type="hidden" name="quantity" value="1" />'
		. '<button class="urumi-btn urumi-btn--solid" type="submit">Add to cart</button>'
		. '</form>';
}
register_block_type( 'urumi-store/sticky-atc', array(
	'render_callback' => 'urumi_store_sticky_atc_render',
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
