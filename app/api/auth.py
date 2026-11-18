"""鉴权接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Patient
from app.schemas import LoginRequest, LoginResponse, PatientOut
from app.security import create_access_token, get_current_patient
from app.utils import mask_phone

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, summary="患者登录（演示：患者编号 + 手机号）")
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> LoginResponse:
    patient = await session.scalar(select(Patient).where(Patient.patient_no == payload.patient_no))
    if patient is None or patient.phone != payload.phone:
        raise HTTPException(status_code=401, detail="患者编号或手机号不正确")
    return LoginResponse(
        access_token=create_access_token(patient),
        patient=PatientOut(
            id=patient.id,
            patient_no=patient.patient_no,
            name=patient.name,
            phone_masked=mask_phone(patient.phone),
        ),
    )


@router.get("/me", response_model=PatientOut, summary="当前登录患者")
async def me(patient: Patient = Depends(get_current_patient)) -> PatientOut:
    return PatientOut(
        id=patient.id,
        patient_no=patient.patient_no,
        name=patient.name,
        phone_masked=mask_phone(patient.phone),
    )
