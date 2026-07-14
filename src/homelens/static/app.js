const form = document.querySelector("#recommendForm");
const introState = document.querySelector("#introState");
const loadingState = document.querySelector("#loadingState");
const resultsState = document.querySelector("#resultsState");
const submitButton = document.querySelector("#submitButton");

const money = new Intl.NumberFormat("en-SG", {
  style: "currency",
  currency: "SGD",
  maximumFractionDigits: 0,
});

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const sliderIds = ["affordability", "space", "lease", "location", "transit", "amenities", "market"];
let weightsTouched = false;
sliderIds.forEach((id) => {
  const input = document.querySelector(`#${id}`);
  const output = document.querySelector(`#${id}Value`);
  input.addEventListener("input", () => {
    output.value = input.value;
    weightsTouched = true;
  });
});

async function loadHealth() {
  const badge = document.querySelector("#healthBadge");
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    if (health.status === "ready") {
      badge.classList.add("ready");
      badge.innerHTML = `<span></span>${health.candidate_rows.toLocaleString()} candidates · through ${escapeHtml(health.latest_observation_month || "unknown")}`;
    } else {
      badge.innerHTML = "<span></span>Setup required · build dataset first";
    }
    const list = document.querySelector("#townList");
    (health.towns || []).forEach((town) => {
      const option = document.createElement("option");
      option.value = town;
      list.append(option);
    });
    const llmAvailable = Boolean(health.integrations?.openai);
    document.querySelector("#useLlm").disabled = !llmAvailable;
    document.querySelector("#llmOption").classList.toggle("unavailable", !llmAvailable);
  } catch (error) {
    badge.innerHTML = "<span></span>Server status unavailable";
  }
}

document.querySelector("#sampleButton").addEventListener("click", () => {
  document.querySelector("#query").value = "A spacious 4-room flat under 650k, preferably in Tampines, with a long remaining lease.";
  document.querySelector("#budget").value = "650000";
  document.querySelector("#towns").value = "Tampines";
  document.querySelectorAll("#flatTypes input").forEach((input) => {
    input.checked = input.value === "4 ROOM";
  });
});

function showState(name) {
  introState.classList.toggle("hidden", name !== "intro");
  loadingState.classList.toggle("hidden", name !== "loading");
  resultsState.classList.toggle("hidden", name !== "results");
}

function selectedFlatTypes() {
  return [...document.querySelectorAll("#flatTypes input:checked")].map((input) => input.value);
}

function payloadFromForm() {
  const towns = document.querySelector("#towns").value
    .split(",")
    .map((town) => town.trim().toUpperCase())
    .filter(Boolean);
  const payload = {
    query: document.querySelector("#query").value.trim(),
    top_k: Number(document.querySelector("#topK").value),
    use_llm: document.querySelector("#useLlm").checked,
  };
  const budget = document.querySelector("#budget").value.trim();
  const flatTypes = selectedFlatTypes();
  if (budget) payload.budget = Number(budget);
  if (flatTypes.length) payload.flat_types = flatTypes;
  if (towns.length) payload.preferred_towns = towns;
  if (weightsTouched) payload.weights = {
      affordability: Number(document.querySelector("#affordability").value),
      space: Number(document.querySelector("#space").value),
      lease: Number(document.querySelector("#lease").value),
      location: Number(document.querySelector("#location").value),
      transit: Number(document.querySelector("#transit").value),
      amenities: Number(document.querySelector("#amenities").value),
      market_activity: Number(document.querySelector("#market").value),
  };
  return payload;
}

function renderWarnings(warnings = []) {
  document.querySelector("#warningBox").innerHTML = warnings
    .map((warning) => `<p class="warning">${escapeHtml(warning)}</p>`)
    .join("");
}

function metric(label, value) {
  return `<div class="metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`;
}

function breakdownBars(scores) {
  const labels = {
    affordability: "Affordability",
    space: "Space",
    lease: "Lease",
    location: "Preferred town",
    transit: "Transit",
    amenities: "Amenities",
    market_activity: "Evidence",
  };
  return Object.entries(labels).map(([key, label]) => {
    const value = scores[key];
    const width = value == null ? 0 : Math.round(value * 100);
    const missing = value == null ? " missing" : "";
    return `<span class="bar${missing}" title="${escapeHtml(label)}: ${value == null ? "unknown" : width + "%"}"><i style="width:${width}%"></i></span>`;
  }).join("");
}

function renderCard(item) {
  const badges = [
    item.preferred_town_match ? '<span class="badge">Preferred town</span>' : "",
    item.pareto_efficient ? '<span class="badge pareto">Pareto option</span>' : "",
    item.evidence_strength === "low" ? '<span class="badge low-evidence">Low sample</span>' : "",
  ].join("");
  return `
    <article class="result-card">
      <div class="card-top">
        <span class="rank">${item.rank}</span>
        <div class="card-title">
          <h3>${escapeHtml(item.block_address)}</h3>
          <p>${escapeHtml(item.town)} · ${escapeHtml(item.flat_type)} · ${escapeHtml(item.flat_model)}</p>
        </div>
        <div class="score"><strong>${Math.round(item.ranking_score * 100)}</strong><small>fit score</small></div>
      </div>
      <div class="badges">${badges}</div>
      <div class="metrics">
        ${metric("Observed median", money.format(item.median_resale_price))}
        ${metric("Middle 50%", `${money.format(item.observed_price_low)}–${money.format(item.observed_price_high)}`)}
        ${metric("Typical size", `${Math.round(item.median_floor_area_sqm)} sqm`)}
        ${metric("Remaining lease", `${item.median_remaining_lease_years.toFixed(1)} yrs`)}
        ${item.ml_reference_price == null ? "" : metric("ML reference", money.format(item.ml_reference_price))}
      </div>
      <ul class="evidence">${item.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
      <div class="breakdown" aria-label="Score breakdown">${breakdownBars(item.score_breakdown)}</div>
    </article>`;
}

function renderEmpty(data) {
  const misses = (data.near_misses || []).map((item) =>
    `<div class="near-miss"><strong>${escapeHtml(item.block_address)}</strong>, ${escapeHtml(item.town)} — budget reference ${money.format(item.budget_reference_price)} (${money.format(item.over_budget_by)} over)</div>`
  ).join("");
  return `<div class="empty-state"><h3>No silent compromises.</h3><p>No option satisfies every hard constraint. Try raising the budget or selecting another flat type.</p>${misses}</div>`;
}

function renderResults(data) {
  const count = data.recommendations.length;
  document.querySelector("#resultsTitle").textContent = count ? "Best-fitting options" : "No exact match";
  document.querySelector("#resultCount").textContent = `${data.eligible_candidate_count.toLocaleString()} eligible of ${data.total_candidate_count.toLocaleString()} candidates`;
  renderWarnings(data.warnings);
  const modelBox = document.querySelector("#modelContext");
  const model = data.model_context;
  if (model?.available) {
    const mape = model.holdout_mape_percent == null ? "not reported" : `${Number(model.holdout_mape_percent).toFixed(2)}% MAPE`;
    const mae = model.holdout_mae == null ? "" : ` · ${money.format(model.holdout_mae)} MAE`;
    modelBox.textContent = `ML reference context: trained through ${model.training_end_month || "unknown"}; chronological holdout ${mape}${mae}. Reference only, not a valuation.`;
    modelBox.classList.remove("hidden");
  } else {
    modelBox.textContent = "";
    modelBox.classList.add("hidden");
  }
  document.querySelector("#cards").innerHTML = count
    ? data.recommendations.map(renderCard).join("")
    : renderEmpty(data);
  document.querySelector("#disclaimer").textContent = data.disclaimer || "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showState("loading");
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadFromForm()),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Recommendation request failed.");
    renderResults(data);
  } catch (error) {
    renderWarnings([error.message]);
    document.querySelector("#cards").innerHTML = '<div class="empty-state"><h3>Could not run the search.</h3><p>Check that the dataset has been built and try again.</p></div>';
  } finally {
    submitButton.disabled = false;
    showState("results");
  }
});

loadHealth();
