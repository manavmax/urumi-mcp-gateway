/*
 * Loam & Ember - storefront behaviours (vanilla JS, no dependencies).
 *
 * 1. Product search suggestions: while typing in a search field, products are
 *    fetched from the site's own Store API (same origin, no third party) and
 *    offered in a keyboard-navigable listbox. Enter still submits the form.
 * 2. Sticky add-to-cart bar on mobile product pages: shown when the main
 *    add-to-cart form scrolls out of view.
 * 3. Price filter guard: blank min/max fields are disabled on submit so an
 *    empty field never narrows the grid.
 * 4. Mobile menu: aria-expanded follows the checkbox state.
 */

(function () {
	"use strict";

	/* ---------- 1. search suggestions ---------- */

	function buildSuggestionPanel(input) {
		var panel = document.createElement("div");
		panel.className = "urumi-suggest";
		panel.setAttribute("role", "listbox");
		panel.setAttribute("aria-label", "Search suggestions");
		panel.hidden = true;
		input.parentNode.appendChild(panel);
		return panel;
	}

	function priceText(p) {
		var cents = p.prices;
		if (!cents || cents.price === undefined) {
			return "";
		}
		var symbol = cents.currency_symbol || "$";
		var n = parseInt(cents.price, 10) / Math.pow(10, parseInt(cents.minor_units || 2, 10));
		var value = n.toFixed(2);
		if (cents.price_range && cents.price_range.min_amount !== cents.price_range.max_amount) {
			return "from " + symbol + (parseInt(cents.price_range.min_amount, 10) / Math.pow(10, parseInt(cents.minor_units || 2, 10))).toFixed(2);
		}
		return symbol + value;
	}

	function optionFor(item) {
		var a = document.createElement("a");
		a.className = "urumi-suggest__option";
		a.setAttribute("role", "option");
		a.href = item.permalink || "#";
		var thumb = document.createElement("span");
		thumb.className = "urumi-suggest__thumb urumi-frame";
		var img = item.images && item.images.length ? item.images[0].thumbnail : "";
		if (img) {
			var i = document.createElement("img");
			i.src = img;
			i.alt = "";
			i.loading = "lazy";
			i.decoding = "async";
			thumb.appendChild(i);
		} else {
			thumb.className += " urumi-photo--empty";
		}
		var name = document.createElement("span");
		name.className = "urumi-suggest__name";
		name.textContent = item.name;
		var price = document.createElement("span");
		price.className = "urumi-suggest__price";
		price.textContent = priceText(item);
		a.appendChild(thumb);
		a.appendChild(name);
		a.appendChild(price);
		return a;
	}

	function attachSuggestions(input) {
		var form = input.closest("form");
		if (!form) {
			return;
		}
		var panel = buildSuggestionPanel(input);
		var timer = null;
		var items = [];
		var active = -1;

		function setOpen(open) {
			panel.hidden = !open;
			input.setAttribute("aria-expanded", open ? "true" : "false");
			if (!open) {
				active = -1;
				highlight();
			}
		}

		function highlight() {
			var nodes = panel.querySelectorAll(".urumi-suggest__option");
			nodes.forEach(function (n, idx) {
				n.classList.toggle("is-active", idx === active);
				if (idx === active) {
					n.setAttribute("aria-selected", "true");
				} else {
					n.removeAttribute("aria-selected");
				}
			});
			if (active >= 0 && nodes[active]) {
				nodes[active].scrollIntoView({ block: "nearest" });
			}
		}

		function render(list, term) {
			items = list;
			panel.textContent = "";
			if (!items.length) {
				setOpen(false);
				return;
			}
			items.forEach(function (item) {
				panel.appendChild(optionFor(item));
			});
			var all = document.createElement("a");
			all.className = "urumi-suggest__all";
			all.href = form.getAttribute("action") + "?s=" + encodeURIComponent(term) + "&post_type=product";
			all.textContent = "See all results for \u201C" + term + "\u201D";
			panel.appendChild(all);
			setOpen(true);
		}

		input.setAttribute("role", "combobox");
		input.setAttribute("aria-expanded", "false");
		input.setAttribute("aria-autocomplete", "list");
		input.setAttribute("aria-controls", null);

		input.addEventListener("input", function () {
			var term = input.value.trim();
			if (timer) {
				clearTimeout(timer);
			}
			if (term.length < 2) {
				setOpen(false);
				return;
			}
			timer = setTimeout(function () {
				var url =
					"/wp-json/wc/store/v1/products?per_page=5&search=" +
					encodeURIComponent(term);
				fetch(url, { headers: { Accept: "application/json" } })
					.then(function (r) {
						return r.ok ? r.json() : [];
					})
					.then(function (list) {
						if (input.value.trim() === term) {
							render(list, term);
						}
					})
					.catch(function () {
						setOpen(false);
					});
			}, 200);
		});

		input.addEventListener("keydown", function (e) {
			if (panel.hidden) {
				return;
			}
			var nodes = Array.prototype.slice.call(panel.querySelectorAll(".urumi-suggest__option"));
			if (e.key === "ArrowDown") {
				e.preventDefault();
				active = (active + 1) % nodes.length;
				highlight();
			} else if (e.key === "ArrowUp") {
				e.preventDefault();
				active = (active - 1 + nodes.length) % nodes.length;
				highlight();
			} else if (e.key === "Escape") {
				setOpen(false);
			} else if (e.key === "Enter" && active >= 0 && nodes[active]) {
				e.preventDefault();
				window.location.href = nodes[active].href;
			}
		});

		document.addEventListener("click", function (e) {
			if (!panel.hidden && !panel.contains(e.target) && e.target !== input) {
				setOpen(false);
			}
		});

		input.addEventListener("blur", function () {
			setTimeout(function () {
				setOpen(false);
			}, 150);
		});
	}

	document
		.querySelectorAll(".urumi-search-input")
		.forEach(attachSuggestions);

	/* ---------- 2. sticky add-to-cart bar (mobile product pages) ---------- */

	var sticky = document.querySelector("[data-urumi-sticky-atc]");
	var form = document.querySelector("form.cart");
	if (sticky && form && "IntersectionObserver" in window) {
		var io = new IntersectionObserver(
			function (entries) {
				var visible = entries[0].isIntersecting;
				var show = !visible && window.matchMedia("(max-width: 767px)").matches;
				sticky.hidden = !show;
				document.body.classList.toggle("has-sticky-atc", show);
			},
			{ threshold: 0 }
		);
		io.observe(form);
		window.addEventListener("resize", function () {
			if (!window.matchMedia("(max-width: 767px)").matches && !sticky.hidden) {
				sticky.hidden = true;
				document.body.classList.remove("has-sticky-atc");
			}
		});
	}

	/* ---------- 3. price filter: never submit blank fields ---------- */

	document.querySelectorAll("[data-urumi-price-filter]").forEach(function (f) {
		f.addEventListener("submit", function () {
			f.querySelectorAll("input[name=min_price], input[name=max_price]").forEach(function (el) {
				if (el.value.trim() === "") {
					el.disabled = true;
				}
			});
		});
	});

	/* ---------- 4. mobile menu aria-expanded ---------- */

	var toggle = document.getElementById("urimi-menu-toggle");
	var button = document.querySelector(".urumi-menu-button");
	if (toggle && button) {
		toggle.addEventListener("change", function () {
			button.setAttribute("aria-expanded", toggle.checked ? "true" : "false");
			button.setAttribute("aria-label", toggle.checked ? "Close menu" : "Open menu");
		});
	}
})();
