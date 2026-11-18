"""All ORM models – imported here so Alembic autogenerate and the app see the full schema."""
from app.models.assistant import AssistantMessage, AssistantProposal
from app.models.audit import AuditLog, Document, IngestionBatch, IngestionRecord, PriorityHistory
from app.models.caregap import CareGapAlert
from app.models.clinical import Appointment, Consultation, DiagnosticTest, Prescription, Referral, TestResultValue
from app.models.core import AppSetting, AuthSession, Department, IdSequence, User, UserDepartment
from app.models.patient import Allergy, CarePlan, Diagnosis, Medication, MedicalHistory, Patient
from app.models.workflow import Notification, Reminder, Task, TaskEvent

__all__ = ['AssistantMessage', 'AssistantProposal', 'CareGapAlert', 'AuditLog', 'Document', 'IngestionBatch', 'IngestionRecord', 'PriorityHistory',
           'Appointment', 'Consultation', 'DiagnosticTest', 'Prescription', 'Referral', 'TestResultValue', 'AppSetting', 'AuthSession', 'Department',
           'IdSequence', 'User', 'UserDepartment', 'Allergy', 'CarePlan', 'Diagnosis', 'Medication', 'MedicalHistory', 'Patient', 'Notification',
           'Reminder', 'Task', 'TaskEvent']
