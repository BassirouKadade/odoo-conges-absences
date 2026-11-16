# Journal des modifications

Toutes les évolutions notables du module **Congés & Absences** (`insea_hr_leave_custom`).
Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet respecte le [versionnage sémantique](https://semver.org/lang/fr/).

## [1.0.0] – 2026-11-16

### Ajouté
- Autorisations de sortie (≤ 4 h, le même jour) avec plafond mensuel de 3 sorties ou 8 heures.
- Congés légaux : congé payé annuel, congés exceptionnels (mariage, naissance, décès), congé maladie.
- Circuit de validation Brouillon → Soumis → Validé manager → Approuvé / Refusé, motif de refus obligatoire.
- Contrôles : solde de congés (1,5 jour acquis par mois), non-chevauchement, délai de prévenance de 7 jours, justificatif obligatoire.
- Groupes Employé / Manager / Responsable RH, droits d'accès et règles d'enregistrement.
- Vues formulaire, liste, kanban, calendrier, tableau croisé et graphique ; filtres de recherche.
- Activités et notifications par e-mail ; tâche planifiée d'acquisition mensuelle.
- 49 tests automatisés et jeu de démonstration « Lambda ».
- Pile Docker Compose (Odoo 19, PostgreSQL 16, Mailpit), diagrammes UML et rapport technique.

[1.0.0]: https://github.com/BassirouKadade/odoo-conges-absences/releases/tag/v1.0.0
