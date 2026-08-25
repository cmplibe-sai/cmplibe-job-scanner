// JobPulse Pro Frontend Application Logic
document.addEventListener("DOMContentLoaded", () => {
  // State
  let currentMainTab = "explorer"; // "explorer", "radar", "settings"
  let currentView = "jobs";        // "jobs" or "posts"
  let searchMode = "role";          // "role" or "company"
  let allJobs = [];
  let allPosts = [];
  let pollInterval = null;
  let isFavoriteFilterActive = false;
  let scrapeStartTime = null;

  // DOM Elements
  const scrapeForm = document.getElementById("scrape-form");
  const atsForm = document.getElementById("ats-form");
  const btnStartScrape = document.getElementById("btn-start-scrape");
  const btnAtsScrape = document.getElementById("btn-ats-scrape");
  const btnFavoritesToggle = document.getElementById("btn-favorites-toggle");
  
  const progressBox = document.getElementById("scrape-progress-container");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressStatusText = document.getElementById("progress-status-text");
  const progressTimeText = document.getElementById("progress-time-text");
  const portalStatusPills = document.getElementById("portal-status-pills");
  
  const keywordsInput = document.getElementById("keywords");
  const labelKeywords = document.getElementById("label-keywords");
  const roleTypeSelect = document.getElementById("role-type-select");
  const locationSelect = document.getElementById("location-select");
  const locationCustom = document.getElementById("location-custom");
  const experienceSelect = document.getElementById("experience-select");
  const workModeSelect = document.getElementById("work-mode-select");

  const btnRefresh = document.getElementById("btn-refresh");
  const jobsGrid = document.getElementById("jobs-grid");
  const postsGrid = document.getElementById("posts-grid");
  const jobsCountBadge = document.getElementById("jobs-count-badge");
  const tabBadgeJobs = document.getElementById("tab-badge-jobs");
  const tabBadgePosts = document.getElementById("tab-badge-posts");

  // Dynamic Search Metrics Elements
  const statTotalJobs = document.getElementById("stat-total-jobs");
  const statTechJobs = document.getElementById("stat-tech-jobs");
  const statNonTechJobs = document.getElementById("stat-nontech-jobs");
  const statHiringPosts = document.getElementById("stat-hiring-posts");
  const navTargetCount = document.getElementById("nav-target-count");

  // =================================================================
  // Indian Standard Time (IST, UTC+05:30) Formatter Helper
  // =================================================================
  function formatISTDate(dateStr) {
    if (!dateStr || dateStr === "Never" || dateStr === "null" || dateStr === "none" || dateStr === "") return "Never";
    try {
      let s = String(dateStr).trim();
      if (!s.includes("+") && !s.includes("Z") && !s.includes("IST")) {
        s += "Z";
      }
      const d = new Date(s);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      }) + " IST";
    } catch (e) {
      return dateStr;
    }
  }

  // =================================================================
  // Team Authentication & Security Controller
  // =================================================================
  let currentAuthUser = null;
  let currentAuthRole = "member";

  async function checkAuth() {
    try {
      const res = await fetch("api/auth/me");
      const data = await res.json();
      const overlay = document.getElementById("auth-overlay");
      const navUsername = document.getElementById("nav-username");

      if (data.authenticated) {
        currentAuthUser = data.user;
        currentAuthRole = data.role || "member";
        if (overlay) overlay.classList.add("hidden");
        if (navUsername) {
          navUsername.innerHTML = `${escapeHtml(data.user)} <span style="font-size: 10px; opacity: 0.75; font-weight: normal; text-transform: uppercase;">(${escapeHtml(currentAuthRole)})</span>`;
        }
        initApp();
      } else {
        currentAuthUser = null;
        currentAuthRole = "member";
        if (overlay) overlay.classList.remove("hidden");
      }
    } catch (err) {
      console.error("Auth check failed:", err);
      const overlay = document.getElementById("auth-overlay");
      if (overlay) overlay.classList.remove("hidden");
    }
  }

  window.handleLogin = async (e) => {
    if (e) e.preventDefault();
    const userEl = document.getElementById("auth-username");
    const passEl = document.getElementById("auth-password");
    const errEl = document.getElementById("auth-error-msg");
    const btn = document.getElementById("btn-auth-submit");

    if (errEl) errEl.classList.add("hidden");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Authenticating...';
    }

    try {
      const resp = await fetch("api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: userEl.value.trim(),
          password: passEl.value,
        }),
      });

      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Invalid username or password");
      }

      currentAuthUser = data.user;
      currentAuthRole = data.role || "member";
      const overlay = document.getElementById("auth-overlay");
      const navUsername = document.getElementById("nav-username");
      if (overlay) overlay.classList.add("hidden");
      if (navUsername) {
        navUsername.innerHTML = `${escapeHtml(data.user)} <span style="font-size: 10px; opacity: 0.75; font-weight: normal; text-transform: uppercase;">(${escapeHtml(currentAuthRole)})</span>`;
      }
      showToast(`Welcome ${data.user}! Signed in successfully.`, "success");
      passEl.value = "";
      initApp();
    } catch (err) {
      if (errEl) {
        errEl.innerText = err.message;
        errEl.classList.remove("hidden");
      }
      showToast(err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> Sign In to Team Portal';
      }
    }
  };

  window.handleLogout = async () => {
    try {
      await fetch("api/auth/logout", { method: "POST" });
    } catch (e) {}
    currentAuthUser = null;
    currentAuthRole = "member";
    const overlay = document.getElementById("auth-overlay");
    if (overlay) overlay.classList.remove("hidden");
    showToast("Signed out successfully.", "info");
  };

  window.handleChangePassword = async (e) => {
    if (e) e.preventDefault();
    const oldPass = document.getElementById("old-password").value;
    const newPass = document.getElementById("new-password").value;

    if (newPass.length < 6) {
      showToast("New password must be at least 6 characters.", "error");
      return;
    }

    const btn = document.getElementById("btn-change-password");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Updating...';
    }

    try {
      const resp = await fetch("api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          old_password: oldPass,
          new_password: newPass,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Failed to update password");
      }
      showToast(data.message || "Password updated successfully!", "success");
      document.getElementById("change-password-form").reset();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-shield-check"></i> Update Password';
      }
    }
  };

  // =================================================================
  // Admin User Management Functions
  // =================================================================

  async function loadTeamUsers() {
    if (currentAuthRole !== "admin") return;
    try {
      const resp = await fetch("api/auth/users");
      if (!resp.ok) return;
      const data = await resp.json();
      const users = data.users || [];
      const tbody = document.getElementById("team-users-tbody");
      if (!tbody) return;

      if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">No team users registered yet.</td></tr>';
        return;
      }

      tbody.innerHTML = users.map(u => {
        const isAdmin = u.role === "admin";
        const isActive = u.is_active === 1;
        const roleBadge = isAdmin
          ? '<span class="badge" style="background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.3);">Admin</span>'
          : '<span class="badge" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.3);">Member</span>';
        
        const statusBadge = isActive
          ? '<span style="color: #10b981; font-weight: 600; font-size: 12px;">● Active</span>'
          : '<span style="color: #ef4444; font-weight: 600; font-size: 12px;">○ Disabled</span>';

        const isSelf = u.username === currentAuthUser;
        const isMasterAdmin = u.username.toLowerCase() === "admin";

        return `
          <tr>
            <td><strong>${escapeHtml(u.username)}</strong> ${isSelf ? '<small style="color: var(--color-primary);">(You)</small>' : ''}</td>
            <td>${roleBadge}</td>
            <td>${statusBadge}</td>
            <td style="color: var(--text-dim); font-size: 11.5px;">${formatISTDate(u.created_at)}</td>
            <td style="color: var(--text-dim); font-size: 11.5px;">${formatISTDate(u.last_login_at)}</td>
            <td>
              <div style="display: flex; gap: 6px;">
                <button type="button" class="btn-icon" onclick="adminResetPassword('${escapeHtml(u.username)}')" title="Reset Password" style="font-size: 11px;">
                  <i class="fa-solid fa-key text-yellow"></i>
                </button>
                ${!isSelf ? `
                  <button type="button" class="btn-icon" onclick="adminToggleStatus('${escapeHtml(u.username)}')" title="${isActive ? 'Deactivate User' : 'Activate User'}" style="font-size: 11px;">
                    <i class="fa-solid ${isActive ? 'fa-user-slash text-orange' : 'fa-user-check text-green'}"></i>
                  </button>
                ` : ''}
                ${!isSelf && !isMasterAdmin ? `
                  <button type="button" class="btn-icon" onclick="adminDeleteUser('${escapeHtml(u.username)}')" title="Delete User" style="font-size: 11px; color: #ef4444;">
                    <i class="fa-solid fa-trash"></i>
                  </button>
                ` : ''}
              </div>
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.error("Failed to load team users:", err);
    }
  }

  window.loadTeamUsers = loadTeamUsers;

  window.handleAddUser = async (e) => {
    if (e) e.preventDefault();
    const unameEl = document.getElementById("new-user-username");
    const pwdEl = document.getElementById("new-user-password");
    const roleEl = document.getElementById("new-user-role");
    const btn = document.getElementById("btn-add-user");

    const username = unameEl.value.trim();
    const password = pwdEl.value;
    const role = roleEl.value;

    if (username.length < 3) {
      showToast("Username must be at least 3 characters.", "error");
      return;
    }
    if (password.length < 6) {
      showToast("Password must be at least 6 characters.", "error");
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating...';
    }

    try {
      const resp = await fetch("api/auth/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Failed to create user");
      }
      showToast(data.message || `User '${username}' created!`, "success");
      document.getElementById("add-user-form").reset();
      loadTeamUsers();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-user-check"></i> Create User Account';
      }
    }
  };

  window.adminResetPassword = async (targetUser) => {
    const newPwd = prompt(`Enter new password for user '${targetUser}' (min 6 characters):`);
    if (!newPwd) return;
    if (newPwd.length < 6) {
      showToast("Password must be at least 6 characters.", "error");
      return;
    }

    try {
      const resp = await fetch(`api/auth/users/${encodeURIComponent(targetUser)}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPwd }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Failed to reset password");
      }
      showToast(data.message || `Password reset for '${targetUser}'!`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.adminToggleStatus = async (targetUser) => {
    try {
      const resp = await fetch(`api/auth/users/${encodeURIComponent(targetUser)}/toggle-status`, {
        method: "POST",
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Failed to update status");
      }
      showToast(data.message || "User status updated!", "success");
      loadTeamUsers();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.adminDeleteUser = async (targetUser) => {
    if (!confirm(`Are you sure you want to permanently delete user '${targetUser}'?`)) return;
    try {
      const resp = await fetch(`api/auth/users/${encodeURIComponent(targetUser)}`, {
        method: "DELETE",
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.message || "Failed to delete user");
      }
      showToast(data.message || `User '${targetUser}' deleted!`, "success");
      loadTeamUsers();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  function initApp() {
    loadJobs();
    loadPosts();
    loadRadarTargets();
    loadRadarSettings();
    loadDiscoveryLogs();
    loadSheetsSettings();

    // If logged in as admin, show user management panel and load users
    const adminCard = document.getElementById("admin-user-management-card");
    if (adminCard) {
      if (currentAuthRole === "admin") {
        adminCard.classList.remove("hidden");
        loadTeamUsers();
      } else {
        adminCard.classList.add("hidden");
      }
    }
  }

  // Initial Auth Check
  checkAuth();

  // =================================================================
  // Main Tab Switcher (Explorer vs Radar vs Discovery vs Sheets vs Settings)
  // =================================================================
  window.switchMainTab = (tabName) => {
    currentMainTab = tabName;
    document.getElementById("nav-tab-explorer").classList.toggle("active", tabName === "explorer");
    document.getElementById("nav-tab-radar").classList.toggle("active", tabName === "radar");
    document.getElementById("nav-tab-discovery").classList.toggle("active", tabName === "discovery");
    document.getElementById("nav-tab-sheets").classList.toggle("active", tabName === "sheets");
    document.getElementById("nav-tab-settings").classList.toggle("active", tabName === "settings");

    const viewExplorer = document.getElementById("view-explorer");
    const viewRadar = document.getElementById("view-radar");
    const viewDiscovery = document.getElementById("view-discovery");
    const viewSheets = document.getElementById("view-sheets");
    const viewSettings = document.getElementById("view-settings");

    if (viewExplorer) viewExplorer.classList.toggle("hidden", tabName !== "explorer");
    if (viewRadar) viewRadar.classList.toggle("hidden", tabName !== "radar");
    if (viewDiscovery) viewDiscovery.classList.toggle("hidden", tabName !== "discovery");
    if (viewSheets) viewSheets.classList.toggle("hidden", tabName !== "sheets");
    if (viewSettings) viewSettings.classList.toggle("hidden", tabName !== "settings");

    if (tabName === "radar") {
      loadRadarTargets();
      loadRadarLogs();
    } else if (tabName === "discovery") {
      loadDiscoveryLogs();
      loadRadarSettings();
    } else if (tabName === "sheets") {
      loadSheetsSettings();
    } else if (tabName === "settings") {
      loadRadarSettings();
    } else if (tabName === "explorer") {
      loadJobs();
      loadPosts();
    }
  };

  // Search Mode Switcher (By Role vs By Company)
  window.setSearchMode = (mode) => {
    searchMode = mode;
    document.getElementById("tab-mode-role").classList.toggle("active", mode === "role");
    document.getElementById("tab-mode-company").classList.toggle("active", mode === "company");

    const categoryPresets = document.getElementById("group-category-presets");
    if (mode === "company") {
      labelKeywords.innerHTML = '<i class="fa-solid fa-building"></i> Company Name';
      keywordsInput.placeholder = "e.g. Jumbotail, Swiggy, Flipkart, Google, Stripe, Zepto";
      if (categoryPresets) categoryPresets.classList.add("hidden");
    } else {
      labelKeywords.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Job Title / Keywords';
      keywordsInput.placeholder = "e.g. Category Manager, HR Recruiter, Python, React";
      if (categoryPresets) categoryPresets.classList.remove("hidden");
    }
    loadJobs();
  };

  // Quick Preset Helper
  window.applyPreset = (roleTitle) => {
    keywordsInput.value = roleTitle;
    window.setSearchMode("role");
    showToast(`Applied preset: ${roleTitle}`, "success");
    loadJobs();
  };

  // Location Selector Helper
  window.handleLocationChange = (val) => {
    if (val === "custom") {
      locationCustom.classList.remove("hidden");
      locationCustom.focus();
    } else {
      locationCustom.classList.add("hidden");
    }
    loadJobs();
    loadPosts();
  };

  function getSelectedLocation() {
    const sel = locationSelect.value;
    if (sel === "custom") {
      return locationCustom.value.trim() || "India";
    }
    return sel;
  }

  // View Switcher (Portal Jobs vs Recruiter Posts)
  window.switchView = (view) => {
    currentView = view;
    document.getElementById("view-tab-jobs").classList.toggle("active", view === "jobs");
    document.getElementById("view-tab-posts").classList.toggle("active", view === "posts");

    if (view === "jobs") {
      jobsGrid.classList.remove("hidden");
      postsGrid.classList.add("hidden");
      document.getElementById("jobs-count-title").innerHTML = `Discovered Opportunities <span class="count-badge" id="jobs-count-badge">${allJobs.length}</span>`;
    } else {
      jobsGrid.classList.add("hidden");
      postsGrid.classList.remove("hidden");
      document.getElementById("jobs-count-title").innerHTML = `Recruiter & HR Hiring Posts <span class="count-badge">${allPosts.length}</span>`;
    }
  };

  // Active Filter Summary Bar Helper
  function updateActiveFiltersBar() {
    const filterBar = document.getElementById("active-filters-bar");
    const filterList = document.getElementById("active-filters-list");
    if (!filterBar || !filterList) return;

    const term = keywordsInput.value.trim();
    const loc = getSelectedLocation();
    const role = roleTypeSelect.value;
    const exp = experienceSelect.value;
    const mode = workModeSelect.value;

    const tags = [];
    if (term) {
      tags.push(`<span class="filter-tag">${searchMode === "role" ? "🔍" : "🏢"} ${escapeHtml(term)} <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('term')"></i></span>`);
    }
    if (loc && loc !== "India" && loc !== "All") {
      tags.push(`<span class="filter-tag">📍 ${escapeHtml(loc)} <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('location')"></i></span>`);
    }
    if (role && role !== "all") {
      tags.push(`<span class="filter-tag">👔 ${role === 'technical' ? 'Technical' : 'Non-Technical'} <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('role')"></i></span>`);
    }
    if (exp) {
      const expText = experienceSelect.options[experienceSelect.selectedIndex].text;
      tags.push(`<span class="filter-tag">🎓 ${escapeHtml(expText)} <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('exp')"></i></span>`);
    }
    if (mode && mode !== "All" && mode !== "") {
      tags.push(`<span class="filter-tag">🏠 ${escapeHtml(mode)} <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('mode')"></i></span>`);
    }
    if (isFavoriteFilterActive) {
      tags.push(`<span class="filter-tag">⭐ Favorites Only <i class="fa-solid fa-xmark tag-close" onclick="removeFilter('favorite')"></i></span>`);
    }

    if (tags.length > 0) {
      filterList.innerHTML = tags.join("");
      filterBar.style.display = "flex";
    } else {
      filterList.innerHTML = '<span style="color: var(--text-dim); font-size: 12px;"><i class="fa-solid fa-check"></i> Showing all positions (no restricting filters active)</span>';
      filterBar.style.display = "flex";
    }
  }

  window.removeFilter = (filterType) => {
    if (filterType === "term") keywordsInput.value = "";
    if (filterType === "location") {
      locationSelect.value = "India";
      locationCustom.classList.add("hidden");
    }
    if (filterType === "role") roleTypeSelect.value = "all";
    if (filterType === "exp") experienceSelect.value = "";
    if (filterType === "mode") workModeSelect.value = "";
    if (filterType === "favorite") {
      isFavoriteFilterActive = false;
      btnFavoritesToggle.classList.remove("active");
    }
    loadJobs();
    loadPosts();
  };

  window.clearAllFilters = () => {
    keywordsInput.value = "";
    locationSelect.value = "India";
    locationCustom.classList.add("hidden");
    roleTypeSelect.value = "all";
    experienceSelect.value = "";
    workModeSelect.value = "";
    isFavoriteFilterActive = false;
    btnFavoritesToggle.classList.remove("active");
    window.setSearchMode("role");
    showToast("All filters cleared. Displaying all opportunities!", "success");
    loadJobs();
    loadPosts();
  };

  // Multi-Portal Live Scrape Submit
  scrapeForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const queryTerm = keywordsInput.value.trim();
    const location = getSelectedLocation();
    const roleType = roleTypeSelect.value;
    const expLevel = experienceSelect.value;
    const workMode = workModeSelect.value;

    const portalCheckboxes = document.querySelectorAll("input[name='portal']:checked");
    const portals = Array.from(portalCheckboxes).map((cb) => cb.value);

    if (portals.length === 0) {
      showToast("Please select at least one portal or channel.", "error");
      return;
    }

    const careerUrls = [];
    if (searchMode === "company" && queryTerm.toLowerCase().includes("jumbotail")) {
      careerUrls.push("https://jumbotail.com/careers/");
    }

    const payload = {
      keywords: searchMode === "role" ? queryTerm : "",
      company_name: searchMode === "company" ? queryTerm : null,
      location: location === "India" ? "" : location,
      search_type: searchMode,
      role_type: roleType,
      experience_level: expLevel || null,
      internship_only: expLevel === "internship",
      remote_only: workMode === "Remote",
      portals: portals,
      career_urls: careerUrls,
      include_linkedin_posts: portals.includes("linkedin_posts"),
      limit: 100,
    };

    btnStartScrape.disabled = true;
    btnStartScrape.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching All Opportunities...';
    progressBox.classList.remove("hidden");
    progressBarFill.style.width = "20%";
    progressStatusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scraping portals & channels in parallel...';
    portalStatusPills.innerHTML = portals.map(p => `<span class="status-pill" id="pill-${p}">${p.toUpperCase()}: running</span>`).join("");
    
    scrapeStartTime = Date.now();

    try {
      const resp = await fetch("api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.message || "Failed to start scrape");
      }

      showToast("Live multi-portal scraping started!", "success");
      startStatusPolling();
    } catch (err) {
      showToast(err.message, "error");
      btnStartScrape.disabled = false;
      btnStartScrape.innerHTML = '<i class="fa-solid fa-play"></i> Fetch All Opportunities';
      progressBox.classList.add("hidden");
    }
  });

  // Direct ATS / Career Page Crawl Submit
  atsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = document.getElementById("ats-url").value.trim();
    const company = document.getElementById("ats-company").value.trim();

    btnAtsScrape.disabled = true;
    btnAtsScrape.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Extracting...';

    try {
      const resp = await fetch("api/scrape/career", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, company, filter: "" }),
      });

      const data = await resp.json();
      showToast(`Discovered ${data.found} openings (${data.new_saved} new saved)!`, "success");
      loadJobs();
    } catch (err) {
      showToast(`Error crawling career page: ${err.message}`, "error");
    } finally {
      btnAtsScrape.disabled = false;
      btnAtsScrape.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Extract All Openings';
    }
  });

  // Polling for live scrape status
  function startStatusPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
      try {
        const resp = await fetch("api/scrape/status");
        const status = await resp.json();

        const elapsedSec = Math.floor((Date.now() - scrapeStartTime) / 1000);
        progressTimeText.innerText = `${elapsedSec}s`;

        if (status.progress) {
          for (const [portal, info] of Object.entries(status.progress)) {
            const pill = document.getElementById(`pill-${portal}`);
            if (pill) {
              if (info.status === "complete") {
                pill.className = "status-pill complete";
                pill.innerText = `${portal.toUpperCase()}: ${info.count || 0}`;
              } else if (info.status === "failed") {
                pill.className = "status-pill failed";
                pill.innerText = `${portal.toUpperCase()}: failed`;
              }
            }
          }
        }

        if (!status.is_running) {
          clearInterval(pollInterval);
          pollInterval = null;
          progressBarFill.style.width = "100%";
          progressStatusText.innerHTML = '<i class="fa-solid fa-circle-check text-success"></i> Scraping complete!';
          
          btnStartScrape.disabled = false;
          btnStartScrape.innerHTML = '<i class="fa-solid fa-play"></i> Fetch All Opportunities';
          
          if (status.last_result) {
            showToast(`Done: ${status.last_result.unique_jobs} unique jobs & ${status.last_result.total_hiring_posts || 0} posts sourced!`, "success");
          }
          
          loadJobs();
          loadPosts();
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1500);
  }

  // Load Stored Jobs with active Left Filter values
  async function loadJobs() {
    try {
      const term = keywordsInput.value.trim();
      const location = getSelectedLocation();
      const roleType = roleTypeSelect.value;
      const expLevel = experienceSelect.value;
      const workMode = workModeSelect.value;

      let url = `api/jobs?limit=500`;
      if (searchMode === "role" && term) {
        url += `&q=${encodeURIComponent(term)}`;
      } else if (searchMode === "company" && term) {
        url += `&company=${encodeURIComponent(term)}`;
      }

      if (location && location.toLowerCase() !== "india" && location.toLowerCase() !== "all") {
        url += `&location=${encodeURIComponent(location)}`;
      }
      if (roleType && roleType !== "all") {
        url += `&role_type=${encodeURIComponent(roleType)}`;
      }
      if (workMode && workMode !== "All" && workMode !== "") {
        url += `&work_mode=${encodeURIComponent(workMode)}`;
      }
      if (expLevel) {
        url += `&experience_level=${encodeURIComponent(expLevel)}`;
      }
      if (isFavoriteFilterActive) {
        url += `&favorite_only=true`;
      }

      const resp = await fetch(url);
      const data = await resp.json();
      allJobs = data.jobs || [];
      renderJobs(allJobs);
      updateDynamicMetrics();
      updateActiveFiltersBar();
      tabBadgeJobs.innerText = allJobs.length;
      if (currentView === "jobs") {
        document.getElementById("jobs-count-title").innerHTML = `Discovered Opportunities <span class="count-badge" id="jobs-count-badge">${allJobs.length}</span>`;
      }
    } catch (err) {
      console.error("Failed to fetch jobs:", err);
    }
  }

  // Load Recruiter Hiring Posts
  async function loadPosts() {
    try {
      const term = keywordsInput.value.trim();
      const location = getSelectedLocation();
      const roleType = roleTypeSelect.value;

      let url = `api/posts?limit=200`;
      if (term) url += `&q=${encodeURIComponent(term)}`;
      if (location && location.toLowerCase() !== "india" && location.toLowerCase() !== "all") {
        url += `&location=${encodeURIComponent(location)}`;
      }
      if (roleType && roleType !== "all") {
        url += `&role_type=${encodeURIComponent(roleType)}`;
      }

      const resp = await fetch(url);
      const data = await resp.json();
      allPosts = data.posts || [];
      renderPosts(allPosts);
      updateDynamicMetrics();
      tabBadgePosts.innerText = allPosts.length;
    } catch (err) {
      console.error("Failed to fetch posts:", err);
    }
  }

  // Update Dynamic Metrics based on current active search results
  function updateDynamicMetrics() {
    statTotalJobs.innerText = allJobs.length;
    
    const techCount = allJobs.filter(j => (j.role_type || "").toLowerCase() === "technical" || (j.category || "").toLowerCase() === "tech").length;
    const nonTechCount = allJobs.length - techCount;
    
    statTechJobs.innerText = techCount;
    statNonTechJobs.innerText = Math.max(0, nonTechCount);
    statHiringPosts.innerText = allPosts.length;
  }

  // Render Job Cards
  function renderJobs(jobs) {
    if (!jobs || jobs.length === 0) {
      jobsGrid.innerHTML = `
        <div class="empty-state">
          <i class="fa-solid fa-magnifying-glass"></i>
          <h3>No Matching Opportunities Found</h3>
          <p>Try modifying your filters on the left or click <a href="javascript:void(0)" onclick="clearAllFilters()" style="color: var(--primary-light); font-weight: bold; text-decoration: underline;">Clear All Filters</a> to display all opportunities.</p>
        </div>
      `;
      return;
    }

    jobsGrid.innerHTML = jobs
      .map((job) => {
        try {
          const rawMode = String(job.work_mode || "").replace(/WorkMode\./g, "").replace(/UNKNOWN/g, "").trim();
          const cleanMode = (!rawMode || rawMode.toLowerCase() === "unknown" || rawMode.toLowerCase() === "not specified") ? "" : rawMode;
          const rawLoc = String(job.location || "").trim();
          const isLocUnspecified = !rawLoc || rawLoc.toLowerCase() === "not specified" || rawLoc.toLowerCase() === "unknown";
          let locDisplay = isLocUnspecified ? "Location: As Announced" : rawLoc;
          if (cleanMode && !locDisplay.toLowerCase().includes(cleanMode.toLowerCase())) {
            locDisplay += ` • ${cleanMode}`;
          }

          const skillsChips = (job.skills || []).slice(0, 5).map(s => `<span class="skill-chip">${escapeHtml(s)}</span>`).join("");
          const announcedDate = job.posted_date || "Recently Posted";
          
          return `
              <div class="job-card" id="job-card-${job.id}">
                <div class="job-card-top">
                  <div class="job-main-info">
                    <h4><a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="job-title-link" title="Open Job Posting">${escapeHtml(job.title || "Untitled Role")} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 13px; opacity: 0.7; margin-left: 4px;"></i></a></h4>
                    <div class="job-company-row">
                      <i class="fa-solid fa-building"></i> ${escapeHtml(job.company || "Company")}
                    </div>
                  </div>
                  <button class="btn-star ${job.is_favorite ? "favorited" : ""}" onclick="toggleJobFavorite('${job.id}')" title="Favorite">
                    <i class="fa-${job.is_favorite ? "solid" : "regular"} fa-star"></i>
                  </button>
                </div>

                <div class="job-tags-row">
                  <span class="tag-badge portal ${portalClass}">
                    <i class="fa-solid fa-bolt"></i> ${escapeHtml(job.source_portal || "Portal")}
                  </span>
                  <span class="tag-badge ${roleBadgeClass}">
                    ${roleLabel}
                  </span>
                  <span class="tag-badge ${workModeClass}">
                    <i class="fa-solid fa-location-dot"></i> ${escapeHtml(locDisplay)}
                  </span>
                  ${job.is_internship ? `<span class="tag-badge internship"><i class="fa-solid fa-graduation-cap"></i> Internship / Fresher</span>` : ""}
                  ${job.experience_text ? `<span class="tag-badge exp"><i class="fa-solid fa-briefcase"></i> ${escapeHtml(job.experience_text)}</span>` : ""}
                  ${job.salary_text ? `<span class="tag-badge salary"><i class="fa-solid fa-money-bill-wave"></i> ${escapeHtml(job.salary_text)}</span>` : ""}
                </div>

                ${skillsChips ? `<div class="skills-container">${skillsChips}</div>` : ""}

                <div class="job-card-footer">
                  <span><i class="fa-regular fa-clock"></i> Announced: <strong>${escapeHtml(announcedDate)}</strong></span>
                  <div class="card-actions">
                    <select class="status-select" onchange="updateJobStatus('${job.id}', this.value)" style="width: auto; padding: 4px 8px; font-size: 11px;">
                      <option value="new" ${job.status === 'new' ? 'selected' : ''}>New</option>
                      <option value="applied" ${job.status === 'applied' ? 'selected' : ''}>Applied</option>
                      <option value="interviewing" ${job.status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                      <option value="archived" ${job.status === 'archived' ? 'selected' : ''}>Archived</option>
                    </select>
                    <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn-apply">
                      Apply on ${escapeHtml(job.source_portal || "Site")} <i class="fa-solid fa-arrow-up-right-from-square"></i>
                    </a>
                  </div>
                </div>
              </div>
          `;
        } catch (err) {
          console.error("Error rendering job card:", err);
          return "";
        }
      })
      .join("");
  }

  // Render Recruiter Hiring Posts
  function renderPosts(posts) {
    if (!posts || posts.length === 0) {
      postsGrid.innerHTML = `
        <div class="empty-state">
          <i class="fa-solid fa-bullhorn"></i>
          <h3>No Recruiter Posts Sourced Yet</h3>
          <p>Include <strong>"Recruiter Posts"</strong> in your search to find job announcements shared by HRs and hiring managers on LinkedIn!</p>
        </div>
      `;
      return;
    }

    postsGrid.innerHTML = posts
      .map((post) => {
        try {
          return `
            <div class="job-card post-card">
              <div class="job-card-top">
                <div class="poster-header">
                  <div class="poster-avatar">
                    <i class="fa-solid fa-user"></i>
                  </div>
                  <div class="poster-details">
                    <h4>${escapeHtml(post.poster_name)}</h4>
                    <p><i class="fa-solid fa-id-badge"></i> ${escapeHtml(post.poster_title || "Recruiter / Hiring Lead")}</p>
                  </div>
                </div>
                ${post.poster_profile_url ? `
                  <a href="${post.poster_profile_url}" target="_blank" class="btn-outline" style="padding: 6px 12px; font-size: 11px;">
                    <i class="fa-brands fa-linkedin"></i> View Profile
                  </a>
                ` : ""}
              </div>

              <div class="job-tags-row">
                <span class="tag-badge portal posts">
                  <i class="fa-solid fa-bullhorn"></i> LinkedIn Post
                </span>
                <span class="tag-badge">
                  <i class="fa-solid fa-briefcase"></i> Role: ${escapeHtml(post.role_title)}
                </span>
                ${post.contact_email ? `<span class="contact-pill"><i class="fa-solid fa-envelope"></i> ${escapeHtml(post.contact_email)}</span>` : ""}
                ${post.contact_phone ? `<span class="contact-pill"><i class="fa-solid fa-phone"></i> ${escapeHtml(post.contact_phone)}</span>` : ""}
              </div>

              <div class="post-snippet">
                "${escapeHtml(post.post_text)}"
              </div>

              <div class="job-card-footer">
                <span>Location: ${escapeHtml(post.location || "India")}</span>
                <div class="card-actions">
                  <a href="${post.post_url}" target="_blank" rel="noopener noreferrer" class="btn-apply">
                    View Post & Connect <i class="fa-solid fa-arrow-up-right-from-square"></i>
                  </a>
                </div>
              </div>
            </div>
          `;
        } catch (err) {
          console.error("Error rendering post:", err);
          return "";
        }
      })
      .join("");
  }

  function getPortalClass(portal) {
    const p = (portal || "").toLowerCase();
    if (p.includes("linkedin")) return "linkedin";
    if (p.includes("internshala")) return "internshala";
    if (p.includes("unstop")) return "unstop";
    if (p.includes("naukri")) return "naukri";
    if (p.includes("foundit") || p.includes("monster")) return "foundit";
    if (p.includes("shine")) return "shine";
    if (p.includes("indeed")) return "indeed";
    return "career";
  }

  // =================================================================
  // TARGET COMPANY RADAR CONTROLLERS
  // =================================================================
  async function loadRadarTargets() {
    try {
      const resp = await fetch("api/radar/targets");
      const data = await resp.json();
      const targets = data.targets || [];
      
      if (navTargetCount) navTargetCount.innerText = targets.length;
      const countEl = document.getElementById("radar-watchlist-count");
      if (countEl) countEl.innerText = targets.length;

      const grid = document.getElementById("radar-targets-grid");
      if (!grid) return;

      if (targets.length === 0) {
        grid.innerHTML = `
          <div class="empty-state">
            <i class="fa-solid fa-building-circle-arrow-right"></i>
            <h4>No Target Companies Added Yet</h4>
            <p>Add companies on the left to monitor their career sites, LinkedIn, and social recruiter feeds 24/7!</p>
          </div>
        `;
        return;
      }

      grid.innerHTML = targets.map(t => {
        const initial = (t.company_name || "C").charAt(0).toUpperCase();
        const lastScan = t.last_scanned_at ? formatISTDate(t.last_scanned_at) : "Not scanned yet";
        const channelChips = (t.channels || []).map(ch => `<span class="radar-channel-chip">${escapeHtml(ch.toUpperCase())}</span>`).join("");

        return `
          <div class="radar-target-card" id="radar-card-${t.id}">
            <div class="radar-target-header">
              <div class="radar-target-title">
                <div class="radar-target-icon">${initial}</div>
                <div>
                  <h4>${escapeHtml(t.company_name)}</h4>
                  <small style="color: var(--text-dim);">${t.is_active ? '<span style="color: var(--success); font-weight: bold;">● Active Radar</span>' : '<span style="color: var(--warning);">○ Paused</span>'}</small>
                </div>
              </div>
              <div class="radar-target-actions">
                <button class="btn-icon" onclick="triggerRadarScan('${t.id}')" title="Scan Company Now"><i class="fa-solid fa-radar"></i></button>
                <button class="btn-icon" onclick="toggleRadarTarget('${t.id}')" title="${t.is_active ? 'Pause' : 'Resume'}"><i class="fa-solid ${t.is_active ? 'fa-pause' : 'fa-play'}"></i></button>
                <button class="btn-icon" onclick="deleteRadarTarget('${t.id}')" title="Remove" style="color: var(--danger);"><i class="fa-solid fa-trash"></i></button>
              </div>
            </div>

            ${t.career_url ? `
              <div style="font-size: 12px; color: var(--accent);">
                <i class="fa-solid fa-link"></i> <a href="${escapeHtml(t.career_url)}" target="_blank" style="color: var(--accent); text-decoration: underline;">${escapeHtml(t.career_url.slice(0, 38))}...</a>
              </div>
            ` : ""}

            <div class="radar-target-channels">
              ${channelChips}
            </div>

            <div class="radar-target-footer">
              <span>Last Scan: <strong>${lastScan}</strong></span>
              <span style="color: var(--primary-light); font-weight: bold;">Found: ${t.last_found_count || 0}</span>
            </div>
          </div>
        `;
      }).join("");

    } catch (err) {
      console.error("Failed to load radar targets:", err);
    }
  }

  window.handleAddRadarTarget = async (e) => {
    e.preventDefault();
    const name = document.getElementById("radar-company-name").value.trim();
    const careerUrl = document.getElementById("radar-career-url").value.trim();
    const keywords = document.getElementById("radar-keywords").value.trim();

    const channelCbs = document.querySelectorAll("input[name='radar-channel']:checked");
    const channels = Array.from(channelCbs).map(cb => cb.value);

    if (!name) {
      showToast("Company name is required.", "error");
      return;
    }

    try {
      const resp = await fetch("api/radar/targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: name,
          career_url: careerUrl,
          keywords: keywords,
          channels: channels,
        }),
      });

      if (!resp.ok) throw new Error("Failed to add target");
      showToast(`Added ${name} to Target Company Radar!`, "success");
      document.getElementById("radar-add-form").reset();
      loadRadarTargets();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.triggerRadarScan = async (targetId) => {
    try {
      showToast("Initiating Radar Scan...", "success");
      const resp = await fetch(`api/radar/scan?target_id=${targetId || ''}`, { method: "POST" });
      if (!resp.ok) throw new Error("Failed to initiate scan");
      showToast("Radar Scan started in background! Check logs shortly.", "success");
      setTimeout(() => {
        loadRadarTargets();
        loadRadarLogs();
        loadJobs();
      }, 4000);
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.triggerFullRadarScan = () => {
    window.triggerRadarScan("");
  };

  window.toggleRadarTarget = async (targetId) => {
    try {
      await fetch(`api/radar/targets/${targetId}/toggle`, { method: "POST" });
      loadRadarTargets();
      showToast("Toggled radar monitoring status", "success");
    } catch (err) {
      showToast("Error updating status", "error");
    }
  };

  window.deleteRadarTarget = async (targetId) => {
    if (!confirm("Remove this company from your radar watchlist?")) return;
    try {
      await fetch(`api/radar/targets/${targetId}`, { method: "DELETE" });
      showToast("Company removed from watchlist", "success");
      loadRadarTargets();
    } catch (err) {
      showToast("Error deleting target", "error");
    }
  };

  async function loadRadarLogs() {
    try {
      const resp = await fetch("api/radar/logs?limit=50");
      const data = await resp.json();
      const logs = data.logs || [];
      const tbody = document.getElementById("radar-logs-tbody");
      if (!tbody) return;

      if (logs.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">No alerts emailed yet. Set up your SMTP settings to start receiving automatic email digests.</td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = logs.map(l => `
        <tr>
          <td><a href="${escapeHtml(l.url)}" target="_blank" style="color: var(--accent); font-weight: 600;">${escapeHtml(l.title)} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 11px;"></i></a></td>
          <td><strong>${escapeHtml(l.company)}</strong></td>
          <td><span class="skill-chip">${escapeHtml(l.source)}</span></td>
          <td>${escapeHtml(l.experience_text || "All Levels")}</td>
          <td><code>${escapeHtml(l.recipient_email)}</code></td>
          <td style="color: var(--text-dim); font-size: 11.5px;">${formatISTDate(l.emailed_at)}</td>
        </tr>
      `).join("");
    } catch (err) {
      console.error("Failed to load radar logs:", err);
    }
  }

  // =================================================================
  // SETTINGS & SMTP EMAIL CONTROLLERS
  // =================================================================
  // =================================================================
  // ALL-INDIA DISCOVERY RADAR CONTROLLERS
  // =================================================================
  async function loadDiscoveryLogs() {
    try {
      const resp = await fetch("api/radar/discovery/logs?limit=50");
      const data = await resp.json();
      const logs = data.logs || [];

      const countEl = document.getElementById("discovery-alerts-count");
      if (countEl) countEl.innerText = logs.length;

      const tbody = document.getElementById("discovery-logs-tbody");
      if (!tbody) return;

      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No All-India alerts sent yet. Run a scan or enable background checks to start receiving alerts.</td></tr>';
        return;
      }

      tbody.innerHTML = logs.map(l => `
        <tr>
          <td><a href="${escapeHtml(l.url)}" target="_blank" style="color: var(--accent); font-weight: 600;">${escapeHtml(l.title)} <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 11px;"></i></a></td>
          <td><strong>${escapeHtml(l.company)}</strong></td>
          <td><span class="skill-chip">${escapeHtml(l.source)}</span></td>
          <td><span class="badge ${l.role_type === 'Technical' ? 'badge-tech' : 'badge-nontech'}">${escapeHtml(l.role_type || 'General')}</span></td>
          <td>${escapeHtml(l.experience_text || "All Levels")}</td>
          <td><code>${escapeHtml(l.recipient_email)}</code></td>
          <td style="color: var(--text-dim); font-size: 11.5px;">${formatISTDate(l.emailed_at)}</td>
        </tr>
      `).join("");
    } catch (err) {
      console.error("Failed to load discovery logs:", err);
    }
  }

  window.loadDiscoveryLogs = loadDiscoveryLogs;

  window.handleTriggerDiscoveryScan = async (e) => {
    if (e) e.preventDefault();
    const btn = document.getElementById("btn-trigger-discovery");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning Portals Across India...';
    }

    const payload = {
      keywords: document.getElementById("discovery-keywords").value.trim(),
      location: document.getElementById("discovery-location").value,
      role_type: document.getElementById("discovery-role-type").value,
      experience_level: document.getElementById("discovery-experience").value || null,
      send_email: document.getElementById("discovery-send-email").checked,
      sync_sheets: document.getElementById("discovery-sync-sheets").checked,
    };

    try {
      const resp = await fetch("api/radar/discovery/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      showToast(data.message || "All-India scan initiated!", "success");
      setTimeout(() => {
        loadDiscoveryLogs();
        loadJobs();
        loadPosts();
      }, 5000);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Trigger All-India Scan Now';
      }
    }
  };

  // =================================================================
  // GOOGLE SHEETS LIVE SYNC CONTROLLERS
  // =================================================================
  let currentSpreadsheetUrl = "";

  async function loadSheetsSettings() {
    try {
      const resp = await fetch("api/sheets/settings");
      const config = await resp.json();

      const enabledEl = document.getElementById("sheets-is-enabled");
      const sheetIdEl = document.getElementById("sheets-spreadsheet-id");
      const credsEl = document.getElementById("sheets-credentials-json");
      const tabAllIndiaEl = document.getElementById("sheet-name-all-india");
      const tabTargetEl = document.getElementById("sheet-name-target-radar");
      const autoSyncEl = document.getElementById("sheets-auto-sync");

      if (enabledEl) enabledEl.checked = !!config.is_enabled;
      if (sheetIdEl) sheetIdEl.value = config.spreadsheet_id_or_url || "";
      if (credsEl && config.credentials_json) credsEl.value = config.credentials_json;
      if (tabAllIndiaEl) tabAllIndiaEl.value = config.sheet_name_all_india || "All-India Jobs";
      if (tabTargetEl) tabTargetEl.value = config.sheet_name_target_radar || "Target Company Radar";
      if (autoSyncEl) autoSyncEl.checked = config.auto_sync_on_scrape !== false;

      // Status metrics
      const badge = document.getElementById("sheets-connection-badge");
      const syncedCount = document.getElementById("sheets-synced-count");
      const lastSync = document.getElementById("sheets-last-sync-time");
      const btnOpen = document.getElementById("btn-open-google-sheet");
      const btnDisconnect = document.getElementById("btn-disconnect-sheets");

      if (syncedCount) syncedCount.innerText = config.last_synced_count || 0;
      if (lastSync) lastSync.innerText = formatISTDate(config.last_synced_at);

      if (config.spreadsheet_id_or_url) {
        currentSpreadsheetUrl = config.spreadsheet_id_or_url.startsWith("http") 
          ? config.spreadsheet_id_or_url 
          : `https://docs.google.com/spreadsheets/d/${config.spreadsheet_id_or_url}/edit`;
        
        if (btnOpen) btnOpen.style.display = "inline-flex";
        if (btnDisconnect) btnDisconnect.style.display = config.is_enabled ? "inline-flex" : "none";

        if (config.is_enabled) {
          if (badge) badge.innerHTML = '<span style="color: #10b981; font-weight: 700;">🟢 Live Sync Connected & Active</span>';
        } else {
          if (badge) badge.innerHTML = '<span style="color: #f59e0b; font-weight: 600;">🟡 Configured (Sync Paused)</span>';
        }
      } else {
        if (badge) badge.innerHTML = '<span style="color: #94a3b8;">⚪ Not Configured</span>';
        if (btnOpen) btnOpen.style.display = "none";
        if (btnDisconnect) btnDisconnect.style.display = "none";
      }
    } catch (err) {
      console.error("Failed to load sheets settings:", err);
    }
  }

  window.loadSheetsSettings = loadSheetsSettings;

  window.handleOpenGoogleSheet = () => {
    if (currentSpreadsheetUrl) {
      window.open(currentSpreadsheetUrl, "_blank");
    } else {
      showToast("No Google Spreadsheet URL configured yet.", "error");
    }
  };

  window.handleDisconnectSheets = async () => {
    if (!confirm("Are you sure you want to disconnect Google Sheets Live Sync? Newly scraped jobs will no longer be streamed to the sheet until reconnected.")) {
      return;
    }
    try {
      const payload = {
        is_enabled: false,
        auto_sync_on_scrape: false,
      };
      const resp = await fetch("api/sheets/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error("Failed to disconnect Google Sheets");
      showToast("Google Sheets disconnected. Live sync is paused.", "info");
      loadSheetsSettings();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.handleSaveSheetsSettings = async (e) => {
    if (e) e.preventDefault();
    const enabledEl = document.getElementById("sheets-is-enabled");
    const sheetId = document.getElementById("sheets-spreadsheet-id").value.trim();
    const creds = document.getElementById("sheets-credentials-json").value.trim();

    // Auto-enable if valid spreadsheet and credentials are provided
    if (sheetId && (creds || document.getElementById("sheets-credentials-json").placeholder.includes("data/")) && !enabledEl.checked) {
      enabledEl.checked = true;
    }

    const payload = {
      is_enabled: enabledEl.checked,
      spreadsheet_id_or_url: sheetId,
      credentials_json: creds,
      sheet_name_all_india: document.getElementById("sheet-name-all-india").value.trim() || "All-India Jobs",
      sheet_name_target_radar: document.getElementById("sheet-name-target-radar").value.trim() || "Target Company Radar",
      auto_sync_on_scrape: document.getElementById("sheets-auto-sync").checked,
    };

    try {
      const resp = await fetch("api/sheets/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error("Failed to save Google Sheets settings");
      showToast("Google Sheets configuration saved and live sync activated!", "success");
      loadSheetsSettings();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.handleTestSheetsConnection = async () => {
    const btn = document.getElementById("btn-test-sheets");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing Connection...';
    }

    const sheetId = document.getElementById("sheets-spreadsheet-id").value.trim();
    const creds = document.getElementById("sheets-credentials-json").value.trim();

    const payload = {
      credentials_json: creds,
      spreadsheet_id_or_url: sheetId,
    };

    try {
      const resp = await fetch("api/sheets/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.message || "Connection test failed");
      }
      
      // Auto-save verified connection so it persists permanently until user disconnects
      const savePayload = {
        is_enabled: true,
        spreadsheet_id_or_url: sheetId,
        credentials_json: creds,
        sheet_name_all_india: document.getElementById("sheet-name-all-india").value.trim() || "All-India Jobs",
        sheet_name_target_radar: document.getElementById("sheet-name-target-radar").value.trim() || "Target Company Radar",
        auto_sync_on_scrape: document.getElementById("sheets-auto-sync").checked,
      };
      await fetch("api/sheets/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(savePayload),
      });

      showToast(data.message + " — Live Sync Connected & Permanently Active!", "success");
      loadSheetsSettings();
    } catch (err) {
      showToast(err.message, "error");
      const badge = document.getElementById("sheets-connection-badge");
      if (badge) badge.innerHTML = '<span style="color: #ef4444;">🔴 Connection Failed</span>';
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-plug"></i> Test Connection & Connect';
      }
    }
  };

  window.handleSyncAllToSheets = async () => {
    try {
      const resp = await fetch("api/sheets/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sync_all: true, limit: 1000 }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.message || "Sync request failed");
      showToast(data.message || "Synchronization started in background!", "success");
      setTimeout(loadSheetsSettings, 4000);
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.handleCleanGoogleSheet = async () => {
    const btn = document.getElementById("btn-clean-sheets");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Cleaning...';
    }

    try {
      const resp = await fetch("api/sheets/clean", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.message || "Failed to clean Google Sheet");
      }
      showToast(data.message || "Google Sheet cleaned successfully!", "success");
      setTimeout(loadSheetsSettings, 1500);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-broom"></i> Clean Non-Job Rows';
      }
    }
  };

  // =================================================================
  // SETTINGS & SMTP EMAIL CONTROLLERS
  // =================================================================
  async function loadRadarSettings() {
    try {
      const resp = await fetch("api/radar/settings");
      const config = await resp.json();

      const hostEl = document.getElementById("smtp-host");
      const portEl = document.getElementById("smtp-port");
      const userEl = document.getElementById("smtp-user");
      const senderEl = document.getElementById("sender-email");

      // Radar 1: Target Watchlist
      const recipientEl = document.getElementById("recipient-email");
      const enabledEl = document.getElementById("settings-is-enabled");
      const intervalEl = document.getElementById("settings-interval");

      // Radar 2: All-India Discovery
      const allIndiaRecipEl = document.getElementById("all-india-recipient");
      const allIndiaEnabledEl = document.getElementById("settings-all-india-enabled");
      const allIndiaIntervalEl = document.getElementById("all-india-interval");

      // Top Overview displays
      const discoveryRecipDisplay = document.getElementById("discovery-recipient-display");
      const discoveryIntervalDisplay = document.getElementById("discovery-interval-display");

      if (hostEl) hostEl.value = config.smtp_host || "smtp.gmail.com";
      if (portEl) portEl.value = config.smtp_port || 465;
      if (userEl) userEl.value = config.smtp_user || "";
      if (senderEl) senderEl.value = config.sender_email || "";

      if (recipientEl) recipientEl.value = config.recipient_email || "";
      if (enabledEl) enabledEl.checked = !!config.is_enabled;
      if (intervalEl) intervalEl.value = config.check_interval_minutes || 60;

      const aiRecipient = config.all_india_recipient || config.recipient_email || "";
      if (allIndiaRecipEl) allIndiaRecipEl.value = aiRecipient;
      if (allIndiaEnabledEl) allIndiaEnabledEl.checked = !!config.all_india_is_enabled;
      if (allIndiaIntervalEl) allIndiaIntervalEl.value = config.all_india_interval_minutes || 120;

      if (discoveryRecipDisplay) discoveryRecipDisplay.innerText = aiRecipient || "Not Configured";
      if (discoveryIntervalDisplay) discoveryIntervalDisplay.innerText = `Every ${config.all_india_interval_minutes ? Math.round(config.all_india_interval_minutes/60) : 2} Hours`;
    } catch (err) {
      console.error("Failed to load settings:", err);
    }
  }

  window.applySmtpPreset = (provider) => {
    if (provider === "resend") {
      document.getElementById("smtp-host").value = "resend";
      document.getElementById("smtp-port").value = 443;
      document.getElementById("smtp-user").value = "resend";
      const passEl = document.getElementById("smtp-pass");
      passEl.placeholder = "Paste your Resend API Key (re_...)";
      if (!passEl.value || !passEl.value.startsWith("re_")) {
        passEl.value = "";
      }
      document.getElementById("sender-email").value = "cMPLiBe AIScanner <onboarding@resend.dev>";
      showToast("Applied Resend Cloud HTTPS API Preset (Port 443 - Cloud Firewall Proof)", "success");
    } else if (provider === "gmail_ssl") {
      document.getElementById("smtp-host").value = "smtp.gmail.com";
      document.getElementById("smtp-port").value = 465;
      showToast("Applied Google Workspace / Gmail SSL preset (smtp.gmail.com:465 SSL)", "success");
    } else if (provider === "gmail") {
      document.getElementById("smtp-host").value = "smtp.gmail.com";
      document.getElementById("smtp-port").value = 587;
      showToast("Applied Gmail TLS preset (smtp.gmail.com:587 TLS)", "success");
    } else if (provider === "hostinger") {
      document.getElementById("smtp-host").value = "smtp.hostinger.com";
      document.getElementById("smtp-port").value = 465;
      showToast("Applied Hostinger Email preset (smtp.hostinger.com:465 SSL)", "success");
    } else if (provider === "outlook") {
      document.getElementById("smtp-host").value = "smtp-mail.outlook.com";
      document.getElementById("smtp-port").value = 587;
      showToast("Applied Outlook SMTP preset (smtp-mail.outlook.com:587)", "success");
    } else {
      document.getElementById("smtp-host").value = "";
      document.getElementById("smtp-port").value = 465;
    }
  };

  window.handleTestSmtpConnection = async () => {
    const btn = document.getElementById("btn-test-smtp-conn");
    const badge = document.getElementById("smtp-connection-badge");
    const hostEl = document.getElementById("smtp-host");
    const portEl = document.getElementById("smtp-port");
    const userEl = document.getElementById("smtp-user");
    const passEl = document.getElementById("smtp-pass");

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing Mail Server Connection...';
    }

    const payload = {
      smtp_host: hostEl.value.trim(),
      smtp_port: parseInt(portEl.value.trim() || "465"),
      smtp_user: userEl.value.trim(),
      smtp_password: passEl.value,
    };

    try {
      const resp = await fetch("api/radar/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.message || "Mail server connection failed");
      }
      showToast(data.message, "success");
      if (badge) {
        badge.innerHTML = '<span style="color: #10b981;">🟢 Server Connected & Verified</span>';
        badge.style.borderColor = "rgba(16, 185, 129, 0.4)";
      }
      if (data.recommended_port && portEl) {
        portEl.value = data.recommended_port;
      }
    } catch (err) {
      showToast(err.message, "error");
      if (badge) {
        badge.innerHTML = '<span style="color: #ef4444;">🔴 Connection Failed</span>';
        badge.style.borderColor = "rgba(239, 68, 68, 0.4)";
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-plug"></i> Step 1: Test Mail Server Connection & Authentication';
      }
    }
  };

  window.handleSaveSettings = async (e) => {
    if (e) e.preventDefault();
    const payload = {
      smtp_host: document.getElementById("smtp-host").value.trim(),
      smtp_port: parseInt(document.getElementById("smtp-port").value.trim() || "465"),
      smtp_user: document.getElementById("smtp-user").value.trim(),
      smtp_password: document.getElementById("smtp-pass").value,
      sender_email: document.getElementById("sender-email").value.trim(),
      recipient_email: document.getElementById("recipient-email").value.trim(),
      is_enabled: document.getElementById("settings-is-enabled").checked,
      check_interval_minutes: parseInt(document.getElementById("settings-interval").value),
      all_india_recipient: document.getElementById("all-india-recipient").value.trim(),
      all_india_is_enabled: document.getElementById("settings-all-india-enabled").checked,
      all_india_interval_minutes: parseInt(document.getElementById("all-india-interval").value),
    };

    try {
      const resp = await fetch("api/radar/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) throw new Error("Failed to save settings");
      showToast("Email & Dual Radar settings saved successfully!", "success");
      loadRadarSettings();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  window.handleSendTestEmail = async (alertType = "target") => {
    let recipient = "";
    if (alertType === "all_india") {
      recipient = document.getElementById("all-india-recipient").value.trim();
      if (!recipient) {
        showToast("Please enter an All-India Alert Recipient Email first.", "error");
        document.getElementById("all-india-recipient").focus();
        return;
      }
    } else {
      recipient = document.getElementById("recipient-email").value.trim();
      if (!recipient) {
        showToast("Please enter a Target Radar Recipient Email first.", "error");
        document.getElementById("recipient-email").focus();
        return;
      }
    }

    const payload = {
      recipient_email: recipient,
      alert_type: alertType,
      smtp_host: document.getElementById("smtp-host").value.trim(),
      smtp_port: parseInt(document.getElementById("smtp-port").value.trim() || "465"),
      smtp_user: document.getElementById("smtp-user").value.trim(),
      smtp_password: document.getElementById("smtp-pass").value,
      sender_email: document.getElementById("sender-email").value.trim(),
    };

    try {
      showToast(`Sending test ${alertType === "all_india" ? "All-India" : "Target Radar"} email to ${recipient}...`, "info");
      const resp = await fetch("api/radar/test-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.message || "Failed to send test email");
      }
      showToast(data.message, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  // Left Filter Auto-Listeners
  keywordsInput.addEventListener("input", debounce(loadJobs, 350));
  locationCustom.addEventListener("input", debounce(loadJobs, 350));
  roleTypeSelect.addEventListener("change", () => { loadJobs(); loadPosts(); });
  experienceSelect.addEventListener("change", loadJobs);
  workModeSelect.addEventListener("change", loadJobs);

  btnRefresh.addEventListener("click", () => {
    loadJobs();
    loadPosts();
    showToast("Refreshed listings", "success");
  });

  btnFavoritesToggle.addEventListener("click", () => {
    isFavoriteFilterActive = !isFavoriteFilterActive;
    btnFavoritesToggle.classList.toggle("active", isFavoriteFilterActive);
    loadJobs();
  });

  // Export Trigger with Active Query Parameters
  window.toggleExportMenu = (event) => {
    event.stopPropagation();
    const menu = document.getElementById("export-menu");
    menu.classList.toggle("show");
  };

  window.downloadExport = (format) => {
    const menu = document.getElementById("export-menu");
    if (menu) menu.classList.remove("show");

    if (currentView === "jobs") {
      if (!allJobs || allJobs.length === 0) {
        showToast("No matching job listings to export.", "error");
        return;
      }

      if (format === "csv") {
        const headers = ["Title", "Company", "Role Category", "Location", "Work Mode", "Experience", "Salary", "Skills", "Announced Date", "Portal", "Status", "Apply URL"];
        const rows = allJobs.map(j => [
          `"${(j.title || '').replace(/"/g, '""')}"`,
          `"${(j.company || '').replace(/"/g, '""')}"`,
          `"${(j.role_type || 'Non-Technical').replace(/"/g, '""')}"`,
          `"${(j.location || '').replace(/"/g, '""')}"`,
          `"${(j.work_mode || '').replace(/"/g, '""')}"`,
          `"${(j.experience_text || '').replace(/"/g, '""')}"`,
          `"${(j.salary_text || '').replace(/"/g, '""')}"`,
          `"${((j.skills || []).join(', ')).replace(/"/g, '""')}"`,
          `"${(j.posted_date || 'Recently Posted').replace(/"/g, '""')}"`,
          `"${(j.source_portal || '').replace(/"/g, '""')}"`,
          `"${(j.status || 'new').replace(/"/g, '""')}"`,
          `"${(j.url || '').replace(/"/g, '""')}"`
        ]);

        const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\r\n");
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `cmplibe_aiscanner_jobs_${Date.now()}.csv`;
        link.click();
        showToast(`Exported ${allJobs.length} filtered opportunities to CSV!`, "success");
      } else if (format === "json") {
        const blob = new Blob([JSON.stringify(allJobs, null, 2)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `cmplibe_aiscanner_jobs_${Date.now()}.json`;
        link.click();
        showToast(`Exported ${allJobs.length} jobs to JSON!`, "success");
      } else if (format === "md") {
        let md = `# cMPLiBe's AIScanner Digest (${allJobs.length} Roles Found)\n\n---\n`;
        allJobs.forEach(j => {
          md += `### [${j.title}](${j.url})\n- **Company:** ${j.company}\n- **Role Category:** ${j.role_type || 'Non-Technical'}\n- **Location:** ${j.location} (${j.work_mode})\n- **Announced:** ${j.posted_date || 'Recently Posted'}\n- **Portal:** ${j.source_portal}\n\n---\n`;
        });
        const blob = new Blob([md], { type: "text/markdown" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `cmplibe_aiscanner_digest_${Date.now()}.md`;
        link.click();
        showToast(`Exported ${allJobs.length} jobs to Markdown!`, "success");
      }
    } else {
      if (!allPosts || allPosts.length === 0) {
        showToast("No active recruiter posts to export.", "error");
        return;
      }
      if (format === "csv") {
        const headers = ["Recruiter / Poster", "Title / Role", "Company", "Location", "Email", "Phone", "Announced Date", "Post URL", "Post Snippet"];
        const rows = allPosts.map(p => [
          `"${(p.poster_name || '').replace(/"/g, '""')}"`,
          `"${(p.role_title || '').replace(/"/g, '""')}"`,
          `"${(p.company || '').replace(/"/g, '""')}"`,
          `"${(p.location || '').replace(/"/g, '""')}"`,
          `"${(p.contact_email || '').replace(/"/g, '""')}"`,
          `"${(p.contact_phone || '').replace(/"/g, '""')}"`,
          `"${(p.posted_date || 'Recently Posted').replace(/"/g, '""')}"`,
          `"${(p.post_url || '').replace(/"/g, '""')}"`,
          `"${(p.post_text || '').replace(/"/g, '""')}"`
        ]);
        const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\r\n");
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `cmplibe_aiscanner_recruiter_posts_${Date.now()}.csv`;
        link.click();
        showToast(`Exported ${allPosts.length} recruiter posts to CSV!`, "success");
      }
    }
  };

  document.addEventListener("click", (event) => {
    const menu = document.getElementById("export-menu");
    const trigger = document.getElementById("btn-export-trigger");
    if (menu && menu.classList.contains("show") && !menu.contains(event.target) && !trigger.contains(event.target)) {
      menu.classList.remove("show");
    }
  });

  // Global helper functions
  window.toggleJobFavorite = async (jobId) => {
    try {
      await fetch(`api/jobs/${jobId}/favorite`, { method: "POST" });
      loadJobs();
    } catch (err) {
      console.error(err);
    }
  };

  window.updateJobStatus = async (jobId, status) => {
    try {
      await fetch(`api/jobs/${jobId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      showToast(`Status updated to ${status}`, "success");
    } catch (err) {
      console.error(err);
    }
  };

  function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `<i class="fa-solid ${type === "success" ? "fa-circle-check" : "fa-triangle-exclamation"}"></i> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.remove();
    }, 4500);
  }

  function debounce(fn, delay) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
