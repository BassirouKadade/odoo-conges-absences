{
    'name': "Congés & Absences",
    'version': '19.0.1.0.0',
    'summary': "Autorisations de sortie, congés légaux et validation Manager / RH",
    'description': """
Congés & Absences
=================

Dématérialise la gestion des absences : de la demande de l'employé
jusqu'à la validation finale par les Ressources Humaines.

Deux types de demandes
----------------------
* **Autorisations de sortie** : absences courtes en heures (4 h maximum),
  plafonnées à 3 sorties ou 8 heures par mois, avec un motif obligatoire.
* **Congés légaux** : congé payé annuel, congé exceptionnel pour événement
  familial (mariage, naissance, décès) et congé maladie.

Circuit de validation
---------------------
Brouillon → Soumis → Validation du manager N+1 → Validation RH → Approuvé.
Le refus est possible à chaque niveau, avec un motif obligatoire, et
l'employé est notifié.

Contrôles automatiques
----------------------
* Solde de congés payés acquis à raison de 1,5 jour par mois
* Aucun chevauchement entre deux demandes
* Délai de prévenance de 7 jours pour les congés payés de plus de 3 jours
* Justificatif obligatoire avant la validation finale (maladie, événement
  familial, consultation médicale)

Droits d'accès
--------------
* **Employé** : ses propres demandes et son solde
* **Manager** : les demandes de son équipe
* **Responsable RH** : toutes les demandes, les soldes et le paramétrage

Vues : formulaire avec barre de statut, liste, kanban, calendrier des
départs, tableau croisé et graphique.

Mini-projet Systèmes Intégrés – INSEA, M2SI, 2026/2027.
    """,
    'author': "INSEA - M2SI",
    'maintainer': "INSEA - M2SI",
    'category': 'Human Resources/Time Off',
    'license': 'LGPL-3',
    'icon': '/insea_hr_leave_custom/static/description/icon.svg',
    'depends': ['hr', 'mail'],
    'data': [
        # Sécurité (ordre important : groupes → droits → règles)
        'security/insea_leave_security.xml',
        'security/ir.model.access.csv',
        'security/insea_leave_rules.xml',
        # Données de référence
        'data/ir_sequence_data.xml',
        'data/insea_leave_type_data.xml',
        'data/ir_cron_data.xml',
        # Vues (les actions doivent exister avant les menus)
        'wizard/insea_leave_refuse_wizard_views.xml',
        'views/insea_leave_request_views.xml',
        'views/insea_leave_config_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/insea_leave_demo.xml',
    ],
    'installable': True,
    'application': True,
}
