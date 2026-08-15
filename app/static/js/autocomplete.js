/**
 * Autocomplete component for card name inputs.
 * Attaches typeahead behavior to any text input element.
 *
 * @param {HTMLInputElement} inputElement - The text input to attach autocomplete to
 * @param {Object} [options] - Configuration options
 * @param {string} [options.apiUrl='/api/cards/autocomplete'] - The API endpoint URL
 * @param {number} [options.minChars=2] - Minimum characters before triggering
 * @param {number} [options.debounceMs=250] - Debounce delay in ms
 */
function initAutocomplete(inputElement, options) {
    const config = {
        apiUrl: (options && options.apiUrl) || '/api/cards/autocomplete',
        minChars: (options && options.minChars) || 2,
        debounceMs: (options && options.debounceMs) || 250
    };

    // Generate a unique ID for ARIA references
    const uniqueId = 'ac-' + Math.random().toString(36).substring(2, 9);

    // Internal state
    let activeIndex = -1;
    let suggestions = [];
    let abortController = null;
    let debounceTimer = null;

    // --- DOM Setup ---
    // Wrap the input in a relative-positioned container
    const wrapper = document.createElement('div');
    wrapper.className = 'autocomplete-wrapper';
    wrapper.style.position = 'relative';
    inputElement.parentNode.insertBefore(wrapper, inputElement);
    wrapper.appendChild(inputElement);

    // Disable native browser autocomplete so it doesn't compete
    inputElement.setAttribute('autocomplete', 'off');

    // Set ARIA attributes on input
    inputElement.setAttribute('aria-autocomplete', 'list');
    inputElement.setAttribute('aria-controls', 'autocomplete-list-' + uniqueId);
    inputElement.setAttribute('aria-expanded', 'false');

    // Create the dropdown list
    const dropdown = document.createElement('ul');
    dropdown.id = 'autocomplete-list-' + uniqueId;
    dropdown.className = 'autocomplete-dropdown';
    dropdown.setAttribute('role', 'listbox');
    dropdown.style.display = 'none';
    wrapper.appendChild(dropdown);

    // --- Helper Functions ---

    function openDropdown() {
        dropdown.style.display = '';
        inputElement.setAttribute('aria-expanded', 'true');
    }

    function closeDropdown() {
        dropdown.style.display = 'none';
        inputElement.setAttribute('aria-expanded', 'false');
        activeIndex = -1;
        inputElement.removeAttribute('aria-activedescendant');
    }

    function clearSuggestions() {
        suggestions = [];
        dropdown.innerHTML = '';
        closeDropdown();
    }

    function renderSuggestions() {
        dropdown.innerHTML = '';
        activeIndex = -1;
        inputElement.removeAttribute('aria-activedescendant');

        if (suggestions.length === 0) {
            closeDropdown();
            return;
        }

        suggestions.forEach(function (name, index) {
            const li = document.createElement('li');
            li.setAttribute('role', 'option');
            li.id = 'autocomplete-option-' + uniqueId + '-' + index;
            li.textContent = name;

            li.addEventListener('mousedown', function (e) {
                // Use mousedown instead of click so it fires before blur
                e.preventDefault();
                selectSuggestion(index);
            });

            dropdown.appendChild(li);
        });

        openDropdown();
    }

    function selectSuggestion(index) {
        if (index >= 0 && index < suggestions.length) {
            inputElement.value = suggestions[index];
            clearSuggestions();
            // Dispatch input event so any other listeners are notified
            inputElement.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    function setActiveIndex(newIndex) {
        // Remove highlight from previous item
        const items = dropdown.querySelectorAll('li');
        if (activeIndex >= 0 && activeIndex < items.length) {
            items[activeIndex].classList.remove('autocomplete-active');
            items[activeIndex].removeAttribute('aria-selected');
        }

        activeIndex = newIndex;

        // Add highlight to new item
        if (activeIndex >= 0 && activeIndex < items.length) {
            items[activeIndex].classList.add('autocomplete-active');
            items[activeIndex].setAttribute('aria-selected', 'true');
            inputElement.setAttribute('aria-activedescendant', items[activeIndex].id);
        } else {
            inputElement.removeAttribute('aria-activedescendant');
        }
    }

    // --- Fetch Suggestions ---

    function fetchSuggestions(query) {
        // Cancel any in-flight request
        if (abortController) {
            abortController.abort();
        }
        abortController = new AbortController();

        var url = config.apiUrl + '?q=' + encodeURIComponent(query);

        fetch(url, { signal: abortController.signal })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function (data) {
                suggestions = data;
                renderSuggestions();
            })
            .catch(function (err) {
                // Silently ignore aborted requests
                if (err.name === 'AbortError') {
                    return;
                }
                // On other errors, clear suggestions
                clearSuggestions();
            });
    }

    // --- Event Handlers ---

    inputElement.addEventListener('input', function () {
        var query = inputElement.value.trim();

        // Clear any pending debounce
        if (debounceTimer) {
            clearTimeout(debounceTimer);
            debounceTimer = null;
        }

        // If fewer than minChars, close dropdown immediately
        if (query.length < config.minChars) {
            // Cancel any in-flight request
            if (abortController) {
                abortController.abort();
                abortController = null;
            }
            clearSuggestions();
            return;
        }

        // Debounce the fetch
        debounceTimer = setTimeout(function () {
            fetchSuggestions(query);
        }, config.debounceMs);
    });

    inputElement.addEventListener('keydown', function (e) {
        if (dropdown.style.display === 'none') {
            return;
        }

        var items = dropdown.querySelectorAll('li');

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            var next = activeIndex + 1;
            if (next >= items.length) {
                next = 0;
            }
            setActiveIndex(next);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            var prev = activeIndex - 1;
            if (prev < 0) {
                prev = items.length - 1;
            }
            setActiveIndex(prev);
        } else if (e.key === 'Enter') {
            if (activeIndex >= 0 && activeIndex < items.length) {
                e.preventDefault();
                selectSuggestion(activeIndex);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeDropdown();
        }
    });

    inputElement.addEventListener('blur', function () {
        // Delay closing to allow mousedown on suggestion to fire
        setTimeout(function () {
            closeDropdown();
        }, 200);
    });

    // Return an object for external control if needed
    return {
        close: closeDropdown,
        clear: clearSuggestions
    };
}
