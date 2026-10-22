/* contributors.js — the people listed in the Documentation dialog (templates/documentation.html).
 * One object per person:
 *   name     shown as written
 *   email    optional
 *   github   optional GitHub username: links the profile and shows its avatar
 *   focus    main area of work
 *   also     other areas (optional list)
 *   note     one optional sentence about the work */
window.MOL = window.MOL || {};
MOL.contributors = [
  { name: "Varun Rishi", email: "rishi.iiser@gmail.com", github: "varunrishi",
    focus: "Orchestration", also: ["Property prediction"] },
  { name: "Karnamohit Ranka", email: "karnamohit@hotmail.com", github: "karnamohit",
    focus: "Property tools (validation with quantum chemistry)", also: ["Generation", "Orchestration"] },
  { name: "Anna Elmanova", email: "anna.elmanova.belskaya@gmail.com", github: "aelm-nv",
    focus: "Property prediction" },
  { name: "Nishi", email: "nishimaru30@gmail.com", github: "nishimaru30",
    focus: "Generation", also: ["Property prediction"] },
  { name: "Manish Chandra", email: "manish.chandra.xyz@proton.me", github: "monees007",
    focus: "App Development", also: ["Bulk DFT calculations"] },
  { name: "Rumman", email: "rummanaslam01@gmail.com", github: "Uman-66",
    focus: "Machine learning", also: ["ML training", "Validation"] },
  { name: "Taqi", email: "taqihassan011@gmail.com", github: "taqi-ul-hassan",
    focus: "ML evaluation and dataset quality",
    note: "Can we show that the selected molecules meet the requested criteria, and explain the evidence behind every result?" },
  { name: "Mirna Ashri", email: "mirna.ashri@etu.unistra.fr", github: "Mirna-ASHRI",
    focus: "Documentation", also: ["One-page summary", "Figure", "README"] }
];
