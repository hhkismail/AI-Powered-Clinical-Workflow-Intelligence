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
    ('PT-10934', 'Ahmad Faizal',  45, array['Penicillin', 'Sulfa Drugs'], array['Metformin 500mg'], 'Type 2 Diabetes, Hypertension')
on conflict (patient_id) do nothing;

-- 24 beds across four wards (6 each), plus two scanners that aren't beds.
-- Two beds start out of service so the board shows realistic turnover.
insert into public.hospital_resources (id, resource_name, resource_type, department, wing, status, assigned_to_patient) values
    ('RES-ICU-01',   'Ventilator Bed 01',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-ICU-02',   'Ventilator Bed 02',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-ICU-03',   'Ventilator Bed 03',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-ICU-04',   'Ventilator Bed 04',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-ICU-05',   'Ventilator Bed 05',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-ICU-06',   'Ventilator Bed 06',      'ICU_BED',    'Critical Care', 'West Wing',          'available',   null),
    ('RES-NEURO-01', 'Observation Bed 01',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-NEURO-02', 'Observation Bed 02',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-NEURO-03', 'Observation Bed 03',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-NEURO-04', 'Observation Bed 04',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-NEURO-05', 'Observation Bed 05',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-NEURO-06', 'Observation Bed 06',     'GEN_WARD',   'Neurology',     'Observation Wing B', 'available',   null),
    ('RES-CARD-01',  'Cardiac Monitor Bay 04', 'GEN_WARD',   'Cardiology',    'Wing A',             'available',   null),
    ('RES-CARD-02',  'Cardiac Monitor Bay 02', 'GEN_WARD',   'Cardiology',    'Wing A',             'available',   null),
    ('RES-CARD-03',  'Cardiac Monitor Bay 03', 'GEN_WARD',   'Cardiology',    'Wing A',             'available',   null),
    ('RES-CARD-04',  'Cardiac Monitor Bay 01', 'GEN_WARD',   'Cardiology',    'Wing A',             'available',   null),
    ('RES-CARD-05',  'Cardiac Monitor Bay 05', 'GEN_WARD',   'Cardiology',    'Wing A',             'available',   null),
    ('RES-CARD-06',  'Cardiac Monitor Bay 06', 'GEN_WARD',   'Cardiology',    'Wing A',             'maintenance', null),
    ('RES-EMG-01',   'Triage Bay 02',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available',   null),
    ('RES-EMG-02',   'Triage Bay 01',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available',   null),
    ('RES-EMG-03',   'Triage Bay 03',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available',   null),
    ('RES-EMG-04',   'Triage Bay 04',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available',   null),
    ('RES-EMG-05',   'Triage Bay 05',          'GEN_WARD',   'Emergency',     'Triage Wing',        'available',   null),
    ('RES-EMG-06',   'Triage Bay 06',          'GEN_WARD',   'Emergency',     'Triage Wing',        'cleaning',    null),
    ('RES-MRI-01',   'MRI Suite 1',            'DIAGNOSTIC', 'Radiology',     'Diagnostic Block',   'available',   null),
    ('RES-CT-01',    'CT Scanner 1',           'DIAGNOSTIC', 'Radiology',     'Diagnostic Block',   'available',   null)
on conflict (id) do update set
    resource_name       = excluded.resource_name,
    resource_type       = excluded.resource_type,
    department          = excluded.department,
    wing                = excluded.wing,
    status              = excluded.status,
    assigned_to_patient = excluded.assigned_to_patient;
