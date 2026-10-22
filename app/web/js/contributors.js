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
    also: ["Orchestration", "Property prediction"] },
  { name: "Karnamohit Ranka", email: "karnamohit@hotmail.com", github: "karnamohit",
    also: ["Generation", "Orchestration", "Quantum Chemistry Validation"] },
  { name: "Anna Elmanova", email: "anna.elmanova.belskaya@gmail.com", github: "aelm-nv",
    also: ["Property prediction"] },
  { name: "Nishi", email: "nishimaru30@gmail.com", github: "nishimaru30",
    also: ["Generation","Property prediction"] },
  { name: "Manish Chandra", email: "manish.chandra.xyz@proton.me", github: "monees007",
    also: ["Web App", "Server", "Bulk DFT calculations"] },
  { name: "Rumman", email: "rummanaslam01@gmail.com", github: "Uman-66",
    also: ["ML Training", "Validation"] },
  { name: "Taqi", email: "taqihassan011@gmail.com", github: "taqi-ul-hassan",
     also: ["ML Evaluation", "Dataset Quality"] },
  { name: "Mirna Ashri", email: "mirna.ashri@etu.unistra.fr", github: "Mirna-ASHRI",
   also: ["Documentation"] }
];
