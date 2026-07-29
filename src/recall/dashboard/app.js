(function () {
  "use strict";

  var previewCount = 0;

  function readMeta(name) {
    var node = document.querySelector('meta[name="' + name + '"]');
    return node ? node.getAttribute("content") || "" : "";
  }

  var TOKEN = readMeta("recall-api-token");
  var BASE = readMeta("recall-api-base");

  var tabSearch = document.getElementById("tab-search");
  var tabAsk = document.getElementById("tab-ask");
  var panelSearch = document.getElementById("panel-search");
  var panelAsk = document.getElementById("panel-ask");
  var statusEl = document.getElementById("status");
  var resultsEl = document.getElementById("results");
  var searchForm = document.getElementById("search-form");
  var askForm = document.getElementById("ask-form");
  var askModelOptions = document.getElementById("ask-model-options");

  function switchTab(active) {
    var isSearch = active === "search";
    tabSearch.classList.toggle("active", isSearch);
    tabAsk.classList.toggle("active", !isSearch);
    tabSearch.setAttribute("aria-selected", String(isSearch));
    tabAsk.setAttribute("aria-selected", String(!isSearch));
    panelSearch.classList.toggle("active", isSearch);
    panelAsk.classList.toggle("active", !isSearch);
  }

  tabSearch.addEventListener("click", function () { switchTab("search"); });
  tabAsk.addEventListener("click", function () { switchTab("ask"); });

  function apiRequest(path, options) {
    var headers = { "Authorization": "Bearer " + TOKEN };
    if (options && options.body) {
      headers["Content-Type"] = "application/json";
    }
    return fetch(BASE + path, Object.assign({}, options || {}, { headers: headers })).then(function (resp) {
      return resp.json().then(function (body) {
        return { ok: resp.ok, status: resp.status, body: body };
      });
    });
  }

  function showStatus(message, isError) {
    statusEl.textContent = message || "";
    statusEl.classList.toggle("error", !!isError);
  }

  function clearResults() {
    resultsEl.textContent = "";
  }

  function handleEnvelope(result, onSuccess) {
    var body = result.body || {};
    if (result.ok && body.ok) {
      onSuccess(body.data || {});
      return;
    }
    var error = body.error || {};
    showStatus(error.message || "Request failed", true);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function createBadge(text, className) {
    return el("span", className, text);
  }

  function togglePreview(button, preview, arrow) {
    var expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", expanded ? "false" : "true");
    preview.hidden = expanded;
    arrow.classList.toggle("open", !expanded);
  }

  function renderPreviewCard(hit, options) {
    var card = el("section", "result-card");
    var button = document.createElement("button");
    var previewId = "preview-" + (++previewCount);
    button.type = "button";
    button.className = "result-toggle";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", previewId);

    var title = el("span", "result-title", hit.path || hit.document_id || "Result");
    var meta = el("span", "result-meta");
    if (options && options.reference) {
      meta.appendChild(createBadge("[" + options.reference + "]", "source-ref"));
    }
    if (hit.metadata && hit.metadata.category) {
      meta.appendChild(createBadge(hit.metadata.category, "result-badge"));
    }
    if (hit.metadata && typeof hit.metadata.chunk_index === "number") {
      meta.appendChild(createBadge("chunk " + hit.metadata.chunk_index, "result-badge"));
    }
    var arrow = el("span", "expand-arrow", "▶");
    button.appendChild(title);
    button.appendChild(meta);
    button.appendChild(arrow);
    card.appendChild(button);

    var preview = el("div", "chunk-preview");
    preview.id = previewId;
    preview.hidden = true;
    if (hit.metadata && hit.metadata.summary) {
      preview.appendChild(el("div", "chunk-summary", hit.metadata.summary));
    }
    if (hit.metadata && hit.metadata.tags && hit.metadata.tags.length) {
      var tags = el("div", "chunk-tags");
      hit.metadata.tags.forEach(function (tag) {
        tags.appendChild(createBadge(tag, "chunk-tag"));
      });
      preview.appendChild(tags);
    }
    var content = document.createElement("pre");
    content.textContent = hit.content || "";
    preview.appendChild(content);
    card.appendChild(preview);

    button.addEventListener("click", function () {
      togglePreview(button, preview, arrow);
    });
    return card;
  }

  function populateModels(models) {
    askModelOptions.textContent = "";
    models.forEach(function (model) {
      var option = document.createElement("option");
      option.value = model;
      askModelOptions.appendChild(option);
    });
  }

  function loadModels() {
    apiRequest("/v1/models").then(function (result) {
      handleEnvelope(result, function (data) {
        populateModels((data && data.models) || []);
      });
    }).catch(function () {
      populateModels([]);
    });
  }

  searchForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = document.getElementById("search-query").value.trim();
    if (!query) {
      return;
    }
    var body = {
      query: query,
      limit: parseInt(document.getElementById("search-limit").value, 10) || 5
    };
    var category = document.getElementById("search-category").value.trim();
    var tag = document.getElementById("search-tag").value.trim();
    if (category) {
      body.category = category;
    }
    if (tag) {
      body.tag = tag;
    }

    showStatus("Searching…");
    clearResults();
    apiRequest("/v1/search", {
      method: "POST",
      body: JSON.stringify(body)
    }).then(function (result) {
      handleEnvelope(result, function (data) {
        var hits = (data && data.results) || [];
        showStatus(hits.length ? hits.length + " result(s)" : "No results");
        hits.forEach(function (hit) {
          resultsEl.appendChild(renderPreviewCard(hit));
        });
      });
    }).catch(function (error) {
      showStatus(String(error), true);
    });
  });

  askForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = document.getElementById("ask-question").value.trim();
    if (!question) {
      return;
    }
    var body = {
      question: question,
      limit: parseInt(document.getElementById("ask-limit").value, 10) || 5,
      allow_general_knowledge: document.getElementById("ask-allow-general-knowledge").checked
    };
    var model = document.getElementById("ask-model").value.trim();
    if (model) {
      body.model = model;
    }

    showStatus("Thinking…");
    clearResults();
    apiRequest("/v1/ask", {
      method: "POST",
      body: JSON.stringify(body)
    }).then(function (result) {
      handleEnvelope(result, function (data) {
        showStatus("");
        var answer = el("div", "answer", data.answer || "");
        resultsEl.appendChild(answer);
        if (data.sources && data.sources.length) {
          var sources = el("div", "sources");
          sources.appendChild(el("div", "sources-title", "Sources"));
          data.sources.forEach(function (source) {
            sources.appendChild(renderPreviewCard(source, { reference: source.reference }));
          });
          resultsEl.appendChild(sources);
        }
      });
    }).catch(function (error) {
      showStatus(String(error), true);
    });
  });

  loadModels();
})();
