-- Ophia demo data. All patients are fictional.
--
-- Run after schema.sql. Safe to re-run: patients are inserted if missing, and
-- beds are reset to their demo state (which frees any bed a demo run reserved).
-- For a quick reset of just the beds, run: python tools/reset_demo.py

insert into public.patients (patient_id, name, age, allergies, active_prescriptions, medical_history) values
    ('PT-30554', 'Rajesh Kumar',  62, array['Aspirin'],                  array['Atorvastatin'],    'Post-Myocardial Infarction, Chronic Heart Disease'),
    ('PT-20221', 'Siti Aminah',    8, array['Latex', 'Peanuts'],         array[]::text[],          'Pediatric Asthma'),
    ('PT-40992', 'Michael Wong',  29, array[]::text[],                   array[]::text[],          'Emergency: Possible Tibia Fracture, No chronic history'),
    ('PT-55108', 'Fatimah Zahra', 71, array['Ibuprofen'],                array['Donepezil'],       'Early-stage Alzheimer, GERD'),
    ('PT-10934', 'New Patient',   45, array['Penicillin', 'Sulfa Drugs'], array['Metformin 500mg'], 'Type 2 Diabetes, Hypertension')
on conflict (patient_id) do nothing;

-- RES-CARD-01 starts occupied so the dashboard shows a ward with no free beds.
insert into public.hospital_resources (id, resource_name, resource_type, department, wing, status, assigned_to_patient) values
    ('RES-ICU-01',   'Ventilator Bed 01',      'ICU_BED',    'Critical Care', 'West Wing',          'available', null),
    ('RES-NEURO-01', 'Observation Bed 01',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available', null),
    ('RES-EMG-01',   'Triage Bay 02',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available', null),
    ('RES-CARD-01',  'Cardiac Monitor Bay 04', 'GEN_WARD',   'Cardiology',    'Wing A',             'occupied',  null),
    ('RES-MRI-01',   'MRI Suite 1',            'DIAGNOSTIC', 'Radiology',     'Diagnostic Block',   'available', null)
on conflict (id) do update set
    resource_name       = excluded.resource_name,
    resource_type       = excluded.resource_type,
    department          = excluded.department,
    wing                = excluded.wing,
    status              = excluded.status,
    assigned_to_patient = excluded.assigned_to_patient;
