"use strict";

const byId = (id) => document.getElementById(id);
const externalUrl = (value) => {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
};

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const link = (label, href, className) => {
  const safe = externalUrl(href);
  if (!safe) return null;
  const anchor = element("a", className, label);
  anchor.href = safe;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
};

function renderLinks(container, links, email) {
  container.replaceChildren();
  for (const [label, href] of Object.entries(links || {})) {
    const anchor = link(label, href);
    if (anchor) container.append(anchor);
  }
  if (email) {
    const anchor = element("a", "", email);
    anchor.href = `mailto:${encodeURIComponent(email)}`;
    container.append(anchor);
  }
}

function renderStats(stats) {
  const labels = [
    ["public_repositories", "Public repositories"],
    ["followers", "Followers"],
    ["following", "Following"],
    ["public_stars", "Public stars"],
    ["public_forks", "Public forks"],
  ];
  const container = byId("stats-grid");
  container.replaceChildren();
  for (const [key, label] of labels) {
    const item = element("div", "stat-item");
    item.append(
      element("span", "stat-value", Number(stats[key] || 0).toLocaleString()),
      element("span", "stat-label", label),
    );
    container.append(item);
  }
}

function renderTechnologyStack(technologies) {
  const container = byId("technology-list");
  container.replaceChildren();
  for (const technology of technologies || []) {
    container.append(element("span", "technology-chip", technology));
  }
}

function renderSkills(skills) {
  const container = byId("skills-grid");
  container.replaceChildren();
  for (const [category, entries] of Object.entries(skills || {})) {
    const card = element("article", "skill-card");
    card.append(element("h3", "", category));
    const list = element("div", "technology-list");
    for (const skill of entries) list.append(element("span", "technology-chip", skill));
    card.append(list);
    container.append(card);
  }
}

function projectLink(project) {
  const href = externalUrl(project.repository_url);
  return href ? link(project.title, href) : null;
}

function createProjectCard(project) {
  const card = element("article", "project-card");
  const top = element("div", "project-card-top");
  top.append(element("span", "project-category", project.category || "Other Projects"));
  const flags = element("span", "project-flags");
  if (project.is_new) flags.append(element("span", "flag flag-new", "NEW"));
  if (project.visibility === "private") flags.append(element("span", "flag", "Private project"));
  if (project.is_fork) flags.append(element("span", "flag", "Fork"));
  if (project.archived) flags.append(element("span", "flag", "Archived"));
  if (project.is_empty) flags.append(element("span", "flag", "Empty repository"));
  top.append(flags);
  card.append(top);

  const heading = element("h3", "project-title");
  const titleAnchor = projectLink(project);
  if (titleAnchor) heading.append(titleAnchor);
  else heading.textContent = project.title || "Project";
  card.append(
    heading,
    element("p", "project-description", project.description || ""),
  );

  const imageUrl = externalUrl(project.screenshot);
  if (imageUrl) {
    const image = element("img", "project-image");
    image.src = imageUrl;
    image.alt = `Screenshot for ${project.title || "project"}`;
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    card.append(image);
  }

  const tags = element("div", "project-tags");
  const projectTags = [
    ...(project.technologies || []),
    ...(project.topics || []),
  ];
  for (const tag of [...new Set(projectTags)].slice(0, 9)) {
    tags.append(element("span", "tag", tag));
  }
  if (tags.childElementCount) card.append(tags);

  const footer = element("div", "project-footer");
  if (project.language) footer.append(element("span", "", project.language));
  if (Number.isFinite(project.stars)) footer.append(element("span", "", `★ ${project.stars}`));
  if (project.status) footer.append(element("span", "", project.status));
  if (project.updated_at) {
    const updated = new Date(project.updated_at);
    if (!Number.isNaN(updated.getTime())) {
      footer.append(element("span", "", `Updated ${updated.toLocaleDateString()}`));
    }
  }
  for (const [label, key] of [
    ["Repository", "repository_url"],
    ["Demo", "live_demo"],
    ["README", "readme_url"],
    ["Evidence", "evidence_url"],
  ]) {
    const anchor = link(label, project[key]);
    if (anchor) footer.append(anchor);
  }
  if (footer.childElementCount) card.append(footer);
  return card;
}

function renderProjectSet(container, projects) {
  container.replaceChildren();
  for (const project of projects) container.append(createProjectCard(project));
}

function fillSelect(select, values) {
  const firstOption = select.options[0];
  select.replaceChildren(firstOption);
  for (const value of values) {
    const option = element("option", "", value);
    option.value = value;
    select.append(option);
  }
}

function setupExplorer(projects) {
  const search = byId("project-search");
  const category = byId("category-filter");
  const technology = byId("technology-filter");
  const sort = byId("sort-projects");
  const list = byId("project-list");
  const count = byId("project-count");
  const empty = byId("empty-results");
  const categories = [...new Set(projects.map((project) => project.category).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  const technologies = [...new Set(projects.flatMap((project) => [
    ...(project.technologies || []),
    ...(project.topics || []),
    project.language,
  ]).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  fillSelect(category, categories);
  fillSelect(technology, technologies);

  const update = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const selectedCategory = category.value;
    const selectedTechnology = technology.value;
    const filtered = projects.filter((project) => {
      const searchable = [
        project.title,
        project.description,
        project.category,
        project.language,
        ...(project.technologies || []),
        ...(project.topics || []),
      ].join(" ").toLocaleLowerCase();
      const projectTechnologies = [
        ...(project.technologies || []),
        ...(project.topics || []),
        project.language,
      ];
      return (!query || searchable.includes(query))
        && (!selectedCategory || project.category === selectedCategory)
        && (!selectedTechnology || projectTechnologies.includes(selectedTechnology));
    });

    if (sort.value === "stars") {
      filtered.sort((a, b) => (b.stars ?? -1) - (a.stars ?? -1));
    } else if (sort.value === "name") {
      filtered.sort((a, b) => a.title.localeCompare(b.title));
    } else {
      filtered.sort((a, b) => {
        const first = Date.parse(a.updated_at || "") || 0;
        const second = Date.parse(b.updated_at || "") || 0;
        return second - first || a.title.localeCompare(b.title);
      });
    }
    renderProjectSet(list, filtered);
    count.textContent = `${filtered.length} ${filtered.length === 1 ? "project" : "projects"}`;
    empty.hidden = filtered.length !== 0;
  };

  for (const control of [search, category, technology, sort]) {
    control.addEventListener("input", update);
    control.addEventListener("change", update);
  }
  update();
}

function renderAchievements(achievements) {
  const container = byId("achievements");
  container.replaceChildren();
  if (!achievements || achievements.length === 0) {
    container.append(element(
      "p",
      "achievement-empty",
      "No certifications or achievements have been configured for public display.",
    ));
    return;
  }
  for (const achievement of achievements) {
    const item = element("div", "achievement-item");
    const title = typeof achievement === "string"
      ? achievement
      : achievement.title || achievement.name || "Achievement";
    item.append(element("strong", "", title));
    if (typeof achievement === "object" && achievement.description) {
      item.append(element("span", "", achievement.description));
    }
    if (typeof achievement === "object" && achievement.issuer) {
      item.append(element("span", "", achievement.issuer));
    }
    const url = typeof achievement === "object" ? externalUrl(achievement.url) : null;
    if (url) {
      const anchor = link("View details", url);
      if (anchor) item.append(anchor);
    }
    container.append(item);
  }
}

async function loadPortfolio() {
  byId("current-year").textContent = String(new Date().getFullYear());
  try {
    const response = await fetch("portfolio/data.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`Portfolio data request failed (${response.status}).`);
    const data = await response.json();
    const profile = data.profile || {};
    byId("hero-title").textContent = profile.name || "PrudenceMatrix";
    byId("hero-title-line").textContent = profile.title || "";
    byId("hero-intro").textContent = profile.intro || "";
    byId("about-copy").textContent = profile.about || "";
    renderLinks(byId("hero-links"), profile.links, "");
    renderLinks(byId("contact-links"), profile.links, profile.email);
    if (profile.portfolio_url) {
      const portfolioLink = link("Portfolio", profile.portfolio_url);
      if (portfolioLink) byId("contact-links").append(portfolioLink);
    }
    const cv = externalUrl(profile.cv_url);
    if (cv) {
      const cvLink = byId("cv-link");
      cvLink.href = cv;
      cvLink.target = "_blank";
      cvLink.rel = "noopener noreferrer";
      cvLink.hidden = false;
    }

    renderStats(data.stats || {});
    renderTechnologyStack(data.technology_stack || []);
    renderSkills(data.skills || {});
    renderAchievements(data.achievements || []);

    const projects = data.projects || [];
    renderProjectSet(byId("featured-projects"), projects.filter((project) => project.featured));
    setupExplorer(projects);
    const practical = projects.filter((project) => (
      /cyber|network|research|laboratory|lab/i.test(project.category || "")
    ));
    renderProjectSet(byId("practical-projects"), practical);
    byId("practical-empty").hidden = practical.length !== 0;
  } catch (error) {
    const alert = byId("load-error");
    alert.textContent = `Portfolio data could not be loaded. Run the generator, then serve this folder over HTTP. ${error.message}`;
    alert.hidden = false;
    byId("stats-grid").replaceChildren(element("p", "loading-message", "Public statistics are unavailable."));
  }
}

loadPortfolio();
